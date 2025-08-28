from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

# --- Models for Conversation State ---
class StateMetadata(BaseModel):
    contact_id: str
    current_turn_number: int = 0
    phone_number: Optional[str] = None
    contact_name: Optional[str] = None
    extracted_name: Optional[str] = None
class EntityItem(BaseModel):
    entity: str
    value: Any

class ProductItem(BaseModel):
    plan_name: str
    details_provided: List[str]

class ChecklistItem(BaseModel):
    topic: str
    content: str
    status: str
class QualificationItem(BaseModel):
    topic: str
    status: str
    value: Optional[Any]
    turn_collected: Optional[int]

class TurnRecap(BaseModel):
    turn_number: int
    user_intent: Optional[str]
    agent_action: Optional[str]
    key_info_exchanged: List[str]

class ObjectionItem(BaseModel):
    objection: str
    status: str
    turn_raised: int

class ConversationGoal(BaseModel):
    goal: str
    status: str


class ConversationState(BaseModel):
    metadata: StateMetadata
    prefers_audio: bool = False
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
    is_sales_final_step: bool = False
    budget_accepted: bool = False
    pending_system_operation: Optional[str] = None
    qualification_tracker: List[QualificationItem] = []
    last_turn_recap: Optional[TurnRecap] = None
    unresolved_objections: List[ObjectionItem] = []
    conversation_goals: List[ConversationGoal] = []