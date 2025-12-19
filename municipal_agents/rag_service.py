# -*- coding: utf-8 -*-
"""
RAG Service for Municipal HITL System

Provides policy and precedent retrieval using Pinecone vector database.
Falls back to mock data if API keys are missing or dependencies unavailable.
"""

import os
from typing import List, Dict, Any, Optional
from pathlib import Path

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / ".env"
    load_dotenv(env_path)
except ImportError:
    pass

# Try importing dependencies, mock if missing
try:
    from pinecone import Pinecone, ServerlessSpec
    import openai
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


class RagService:
    """
    RAG service for retrieving relevant policies and historical precedents.
    
    Uses Pinecone for vector storage and OpenAI for embeddings.
    Gracefully degrades to mock data if dependencies/keys are missing.
    """
    
    def __init__(self):
        self.pinecone_key = os.getenv("PINECONE_API_KEY")
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.index_name = "municipal-policy-index"
        self.pc = None
        self.index = None
        self.client = None
        self._initialized = False
        
        if HAS_DEPS and self.pinecone_key and self.openai_key:
            try:
                self.pc = Pinecone(api_key=self.pinecone_key)
                self.client = openai.OpenAI(api_key=self.openai_key)
            except Exception as e:
                print(f"Warning: Error initializing RAG clients: {e}")
        else:
            if not HAS_DEPS:
                print("Warning: RAG dependencies (pinecone-client, openai) missing. Using mock RAG service.")
            elif not self.pinecone_key or not self.openai_key:
                print("Warning: API keys missing. Using mock RAG service.")

    def initialize(self) -> bool:
        """
        Initialize Pinecone index if it doesn't exist.
        
        Returns:
            True if successfully initialized (or already initialized), False otherwise
        """
        if self._initialized:
            return True
            
        if not self.pc:
            self._initialized = True  # Mark as initialized even in mock mode
            return True

        try:
            existing_indexes = [i.name for i in self.pc.list_indexes()]
            if self.index_name not in existing_indexes:
                print(f"Creating Pinecone index: {self.index_name}")
                self.pc.create_index(
                    name=self.index_name,
                    dimension=1536,  # OpenAI text-embedding-3-small dimension
                    metric="cosine",
                    spec=ServerlessSpec(cloud="aws", region="us-east-1")
                )
            self.index = self.pc.Index(self.index_name)
            self._initialized = True
            return True
        except Exception as e:
            print(f"Error initializing Pinecone index: {e}")
            self.index = None
            self._initialized = True
            return False

    def _get_embedding(self, text: str) -> List[float]:
        """Get embedding vector from OpenAI."""
        if not self.client:
            return [0.0] * 1536
            
        try:
            response = self.client.embeddings.create(
                input=text,
                model="text-embedding-3-small"
            )
            return response.data[0].embedding
        except Exception as e:
            print(f"Error getting embedding: {e}")
            return [0.0] * 1536

    def ingest_policy(self, text: str, metadata: Dict[str, Any]) -> bool:
        """
        Ingest a policy document into the vector store.
        
        Args:
            text: The policy text to embed
            metadata: Additional metadata (id, name, etc.)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.index:
            return False

        vector = self._get_embedding(text)
        doc_id = f"policy_{metadata.get('id', hash(text))}"
        
        try:
            self.index.upsert(vectors=[(doc_id, vector, {**metadata, "text": text, "type": "policy"})])
            return True
        except Exception as e:
            print(f"Error ingesting policy: {e}")
            return False

    def ingest_project(self, project_dict: Dict[str, Any]) -> bool:
        """
        Ingest a historical project for precedent retrieval.
        
        Args:
            project_dict: Project data including title, description, outcome, cost
            
        Returns:
            True if successful, False otherwise
        """
        if not self.index:
            return False

        text = f"{project_dict['title']} - {project_dict.get('description', '')} - Outcome: {project_dict.get('outcome', 'unknown')}"
        vector = self._get_embedding(text)
        doc_id = f"project_{project_dict.get('project_id', hash(text))}"
        
        metadata = {
            "type": "project",
            "text": text,
            "title": project_dict.get("title", ""),
            "outcome": project_dict.get("outcome", "completed"),
            "cost": float(project_dict.get("cost", 0)),
            "category": project_dict.get("category", "")
        }
        
        try:
            self.index.upsert(vectors=[(doc_id, vector, metadata)])
            return True
        except Exception as e:
            print(f"Error ingesting project: {e}")
            return False

    def retrieve_context(self, query: str, top_k: int = 3) -> Dict[str, List[str]]:
        """
        Retrieve relevant policies and historical projects.
        
        Args:
            query: Search query (typically project title + description)
            top_k: Number of results to retrieve per type
            
        Returns:
            Dict with 'policies' and 'projects' lists
        """
        if not self.index:
            # Return mock context for testing/fallback
            return self._get_mock_context()

        try:
            vector = self._get_embedding(query)
            results = self.index.query(
                vector=vector, 
                top_k=top_k * 2,  # Get more to filter by type
                include_metadata=True
            )
            
            policies = []
            projects = []
            
            for match in results.matches:
                text = match.metadata.get("text", "")
                doc_type = match.metadata.get("type", "")
                
                if doc_type == "policy" and len(policies) < top_k:
                    policies.append(text)
                elif doc_type == "project" and len(projects) < top_k:
                    outcome = match.metadata.get("outcome", "unknown")
                    projects.append(f"{text}")
                    
            # Fall back to mock if no results
            if not policies and not projects:
                return self._get_mock_context()
                
            return {"policies": policies, "projects": projects}
            
        except Exception as e:
            print(f"Error retrieving context: {e}")
            return self._get_mock_context()

    def _get_mock_context(self) -> Dict[str, List[str]]:
        """Return mock context for testing or when RAG is unavailable."""
        return {
            "policies": [
                "Municipal Code §4.2.1: Projects exceeding $10M require City Council approval and public hearing.",
                "Fiscal Policy FP-2024-03: High-risk infrastructure projects (score ≥6) must demonstrate community benefit exceeding 3x cost.",
                "Safety Mandate SM-101: Legal mandates cannot be rejected without documented alternative compliance path."
            ],
            "projects": [
                "Water Main Replacement (2023): $12M project, approved after 2 council sessions. Completed on time.",
                "Bridge Retrofit Project (2022): $8M, initially rejected for budget, approved in Q2 after reallocation.",
                "Storm Drain Expansion (2024): $15M, delayed 6 months due to environmental review requirements."
            ]
        }

    def seed_data(self) -> bool:
        """
        Seed the vector store with sample policies and historical projects.
        Only populates if the index is empty.
        
        Returns:
            True if seeding occurred or not needed, False on error
        """
        if not self.index:
            print("Using mock data - no seeding needed")
            return True
            
        try:
            # Check if already populated
            stats = self.index.describe_index_stats()
            if stats.total_vector_count > 0:
                print(f"Index already contains {stats.total_vector_count} vectors - skipping seed")
                return True

            print("Seeding Pinecone with sample policies and projects...")
            
            # Sample municipal policies
            policies = [
                {
                    "id": "pol_fiscal_01",
                    "text": "Municipal Code §4.2.1: All infrastructure projects exceeding $10,000,000 require City Council approval, public hearing notification, and fiscal impact assessment."
                },
                {
                    "id": "pol_fiscal_02",
                    "text": "Fiscal Policy FP-2024-03: Projects with risk score ≥6 must demonstrate quantified community benefit exceeding 3x estimated cost before approval."
                },
                {
                    "id": "pol_safety_01",
                    "text": "Safety Mandate SM-101: Legal mandate projects cannot be rejected without documented alternative compliance path approved by City Attorney."
                },
                {
                    "id": "pol_env_01",
                    "text": "Environmental Standard ES-2023-07: Construction near waterways requires 90-day environmental impact assessment and mitigation plan."
                },
                {
                    "id": "pol_budget_01",
                    "text": "Budget Allocation Rule BA-05: Quarterly budget cannot exceed 85% allocation without reserve fund authorization from Finance Director."
                },
                {
                    "id": "pol_priority_01",
                    "text": "Priority Framework PF-2024: Projects affecting >200,000 residents AND risk score ≥6 require expedited dual-review by Operations and Safety committees."
                }
            ]
            
            for policy in policies:
                self.ingest_policy(policy["text"], {"id": policy["id"]})
            
            # Sample historical projects for precedent
            projects = [
                {
                    "project_id": "hist_2023_001",
                    "title": "Downtown Water Main Replacement",
                    "description": "Complete replacement of 60-year-old water main serving downtown district",
                    "category": "water_infrastructure",
                    "outcome": "approved_completed",
                    "cost": 12500000
                },
                {
                    "project_id": "hist_2023_002",
                    "title": "Highway 7 Bridge Structural Retrofit",
                    "description": "Reinforcement of load-bearing elements after safety inspection flagged concerns",
                    "category": "transportation",
                    "outcome": "approved_delayed",
                    "cost": 8200000
                },
                {
                    "project_id": "hist_2022_003",
                    "title": "Riverside Storm Drain Expansion",
                    "description": "Expansion of storm drain capacity to handle increased rainfall patterns",
                    "category": "flood_control",
                    "outcome": "approved_over_budget",
                    "cost": 15000000
                },
                {
                    "project_id": "hist_2022_004",
                    "title": "Hospital Generator Modernization",
                    "description": "Replacement of backup power systems at Central Hospital - legal mandate",
                    "category": "healthcare_facility",
                    "outcome": "approved_expedited",
                    "cost": 11000000
                },
                {
                    "project_id": "hist_2024_005",
                    "title": "Road Resurfacing Program Phase 1",
                    "description": "Pothole repair and resurfacing across residential zones",
                    "category": "road_maintenance",
                    "outcome": "approved_on_budget",
                    "cost": 4500000
                },
                {
                    "project_id": "hist_2023_006",
                    "title": "School Electrical Upgrade Initiative",
                    "description": "Modernization of electrical systems across 15 schools - fire safety mandate",
                    "category": "public_buildings",
                    "outcome": "approved_phased",
                    "cost": 7800000
                }
            ]
            
            for project in projects:
                self.ingest_project(project)
            
            print(f"Seeded {len(policies)} policies and {len(projects)} historical projects")
            return True
            
        except Exception as e:
            print(f"Error seeding data: {e}")
            return False


# Singleton instance for reuse
_rag_service_instance: Optional[RagService] = None

def get_rag_service() -> RagService:
    """Get or create the singleton RAG service instance."""
    global _rag_service_instance
    if _rag_service_instance is None:
        _rag_service_instance = RagService()
        _rag_service_instance.initialize()
        _rag_service_instance.seed_data()
    return _rag_service_instance
