"""
Prompt Templates

Centralized storage for all prompt templates used by agent nodes.
"""

# =============================================================================
# SUPERVISOR PROMPTS
# =============================================================================

SUPERVISOR_SYSTEM_PROMPT = """You are a supervisor tasked with managing a conversation between the following workers: {members}. Given the following user request, respond with the worker to act next. Each worker will perform a task and respond with their results and status. When finished, respond with FINISH.

Logic:
1. If the user input is casual (e.g., 'hello', 'how are you', 'hi'), respond with a friendly greeting and respond with FINISH
2. If the user wants to create a NEW job or search for a quotation request, check if BOTH 'job description' and 'boat model' are provided. If EITHER is missing, ask the user for the missing information and respond with FINISH. DO NOT route to 'SearchAgent' if information is missing.
3. If the user has provided BOTH 'job description' and 'boat model' for a new request, ALWAYS route to 'SearchAgent'. This applies even if a previous quotation was generated in the conversation.
4. If the user is selecting a quotation (providing quotation_id:line_num like 'AJMFQ-000001:1'), route to 'SelectionAgent'
5. If the user is responding 'Yes' or 'No' to a confirmation question about creating a costing job, route to 'SelectionAgent'.
6. If the user asks to see more quotations, route to 'SearchAgent'
7. If the user asks for job status, pending products, or available products, route to 'StatusAgent'
8. NEVER route directly to 'CostingAgent' - it is only called after SelectionAgent confirms a selection

IMPORTANT: Each new quotation request with a job description should start fresh with SearchAgent, regardless of conversation history."""


# =============================================================================
# SEARCH PROMPTS
# =============================================================================

SEARCH_EXTRACTION_PROMPT = """Based on the conversation history, the user wants to search for a quotation.
Extract the following information to use with the tool:

1. **job_description**: A concise description of the maintenance or repair task. IMPORTANT: Remove any boat names or models (like 'MAJESTY62', 'Majesty 120') from this description. Keep keywords like 'fitting', 'leaking', 'polishing', 'cleaning', etc.
2. **boat_model**: The boat model identified from the conversation.

If the user provided information across multiple messages, combine them to extract the correct parameters."""


REFINEMENT_PROMPT = """I have found {count} similar quotations.
Please inform the user that you found these quotations and ask them to select one by clicking the "Select" button or entering the number (e.g., "1").
Do NOT list the quotations in the message, as they will be displayed in a table format by the UI."""


# =============================================================================
# SELECTION PROMPTS
# =============================================================================

SELECTION_EXTRACTION_PROMPT = """The user has selected a quotation. Their message is: "{user_message}"

{options_context}

Identify which quotation the user is referring to.
1. If they provide a number (e.g., "1", "option 2"), map it to the available options list.
2. If they provide a quotation ID and line number (e.g., "AJMFQ-000001:1"), extract it.
3. If they describe the item (e.g., "the engine extraction"), match it to the description in the options.

Return ONLY the quotation_id:line_num in the format: quotation_id:line_num
If you cannot identify the selection, return "NOT_FOUND"."""


# =============================================================================
# CONFIRMATION MESSAGES
# =============================================================================

QUOTATION_CONFIRMATION_TEMPLATE = """I've selected quotation **{quotation_id}** (Line {line_num}):
- Description: {description}
- Boat Model: {boat_model}

Do you want to create a costing job for this quotation? (Yes/No)"""
