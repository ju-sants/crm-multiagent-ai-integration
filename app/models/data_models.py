from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

# --- Models for Hierarchical History ---

class TopicDetail(BaseModel):
    topic_id: str
    title: str
    summary: str
    quality_score: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: Optional[str] = None
    start_index: int
    end_index: int
    full_details: Optional[str] = None
    key_entities: List[str] = []
    sentiment_trend: List[str] = []

class HierarchicalHistory(BaseModel):
    summary_version: str = "1.0"
    last_updated: str
    topics: List[TopicDetail] = []

# --- Models for Conversation State ---

class StateMetadata(BaseModel):
    contact_id: str
    current_turn_number: int = 0
    last_updated: Optional[str] = None
    phone_number: Optional[str] = None
    contact_name: Optional[str] = None

class CommunicationPreference(BaseModel):
    prefers_audio: bool = False
    reason: str = "default"

class EntityItem(BaseModel):
    entity: str
    value: Any
    turn: int

class ProductItem(BaseModel):
    plan_name: str
    details_provided: List[str]
    presented_at_turn: int

class ChecklistItem(BaseModel):
    topic: str
    content: str
    status: str # "pending" or "communicated"

class ConversationState(BaseModel):
    metadata: StateMetadata
    communication_preference: CommunicationPreference = Field(default_factory=CommunicationPreference)
    session_summary: str = "Início da conversa."
    entities_extracted: List[EntityItem] = []
    products_discussed: List[ProductItem] = []
    disclosure_checklist: List[ChecklistItem] = []
    strategic_plan: Optional[Dict[str, Any]] = None
    system_operation_status: Optional[str] = None
    system_action_request: Optional[str] = None
    identified_topic: Optional[str] = None
    operational_context: Optional[str] = None
    user_sentiment_history: List[Dict[str, Any]] = []
    is_plan_acceptable: bool = False
    budget_accepted: bool = False
    pending_system_operation: Optional[str] = None
    topics_at_this_turn: List[str] = []

# --- Models for Customer Profile ---

class CustomerIdentity(BaseModel):
    name: Optional[str] = None
    roles: List[str] = []

class StrategicInsights(BaseModel):
    communication_preferences: Dict[str, str] = {}
    key_motivations: List[str] = []
    potential_frustrations: List[str] = []
    sales_recommendations: List[str] = []

class CustomerAssets(BaseModel):
    vehicles: List[str] = []
    active_plans: List[str] = []
