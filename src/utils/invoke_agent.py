import os
from dotenv import load_dotenv
from typing import AsyncGenerator

from src.utils import logger
from src.services.message_service import MessageService
from src.services.conversation_service import ConversationService
from src.agentic.agents.database_agent import get_database_agent
from src.agentic.agents.inquiry_agent import get_inquiry_agent

# Load environment variables
load_dotenv()

# Import from new agentic structure
from src.agentic.agents.test_agent import get_test_agent
from RAW.modals import Message

async def invoke_agent(conversation_id: int, message_id: int, message_type: str = "default") -> AsyncGenerator[str, None]:
    """
    Invokes the agent for a given conversation using the refactored agentic structure.
    """
    # 1. Fetch Conversation Details

    print(f"Conversation id : {conversation_id} \nmessage_id : {message_id} \nMessage_type : {message_type}")
    conversation = ConversationService.get_conversation(conversation_id)
    if not conversation:
        logger.error(f"Conversation {conversation_id} not found")
        return

    agent_name = conversation.agent or "Agent"

    # 2. Fetch History (DESC order) and User Input
    if message_type == "whatsapp":
        from src.services.whatsapp_service import WhatsAppService
        data_service = WhatsAppService
    elif message_type == "email":
        from src.services.email_service import EmailService
        data_service = EmailService
    else:
        from src.services.message_service import MessageService
        data_service = MessageService

    # Fetch History using the selected service
    desc_history = data_service.get_messages_by_conversation_desc(conversation_id, limit=20)
    full_history = sorted(desc_history, key=lambda m: m.timestamp)
    # print(f"full_history : {full_history}")
    # Filter out the placeholder if it's an assistant message. 
    # For WhatsApp, the message_id often points to the incoming user message itself.
    valid_msgs = []
    for m in full_history:
        if m.role == 'user' and m.content and str(m.content).strip().lower() == '/reset':
            valid_msgs = [] # Clear history up to this point
            continue # Do not include the /reset message itself

        if m.id == message_id:
            if m.role == 'assistant':
                continue # Skip placeholder
        valid_msgs.append(m)

    raw_history = []
    user_input = None
    
    if valid_msgs:
        last_msg = valid_msgs[-1]
        print(f"Last message: {last_msg}")
        if last_msg.role == 'user':
            user_input = last_msg.content
            history_msgs = valid_msgs[:-1]
        else:
            # If the last message isn't user, we might have an issue or this is a system trigger
            logger.warning(f"Last message {last_msg.id} is not user role: {last_msg.role}")
            # For now, we abort if no user input found to drive the agent
            yield "Error: No user input found."
            return
    else:
        yield "Error: No message history found (user input missing)."
        return
        
    # Convert to RAW Messages
    for msg in history_msgs:
        raw_history.append(Message(role=msg.role, content=msg.content))

    logger.debug(f"--- Invoking Agent: {agent_name} ---")
    logger.debug(f"History Length: {len(raw_history)}")

    # 3. Initialize Agent based on agent_name
    
    
    try:
        if agent_name.startswith("DatabaseAgent"):
            # Support format "DatabaseAgent:purchase" to load specific schema
            module = None
            if ":" in agent_name:
                module = agent_name.split(":")[1]
            agent = get_database_agent(user_id=conversation.user_id, history=raw_history, module=module, message_type=message_type)
        elif agent_name.startswith("inquiry"):
            from src.agentic.tools.inquiry.template_handler import (
                is_template_request,
                is_template_format,
                get_template_text,
                handle_template_inquiry,
            )

            # 1. Check if user is asking for the template format
            if is_template_request(user_input):
                yield get_template_text()
                return

            # 2. Check if user submitted an inquiry via template
            if is_template_format(user_input):
                logger.info(f"Processing inquiry template for conversation {conversation_id}")
                sender_phone = None
                if message_type == "whatsapp":
                    from src.services.whatsapp_service import WhatsAppService
                    wa_msg = WhatsAppService.get_message(message_id)
                    if wa_msg:
                        sender_phone = wa_msg.from_number

                async for chunk in handle_template_inquiry(
                    text=user_input,
                    conversation_id=conversation_id,
                    user_id=conversation.user_id,
                    sender_phone=sender_phone,
                ):
                    yield chunk
                return

            # 3. Fallback: Standard step-by-step LLM inquiry flow
            agent = get_inquiry_agent(
                user_id=conversation.user_id,
                history=raw_history,
                conversation_id=conversation_id,
            )
            print("I am inquiry")
        else:
            # Fallback to test agent for other names like "TestAgent" or "Agent"
            agent = get_test_agent(user_id=conversation.user_id, history=raw_history)
    except Exception as e:
        logger.error(f"Failed to initialize agent {agent_name}: {e}")
        yield f"Error initializing agent: {str(e)}"
        return 

    print(f"User Message: {user_input}")
    
    # 4. Stream Response
    try:
        async for chunk in agent(user_input, stream=True):
            if hasattr(chunk, "content") and chunk.content:
                yield chunk.content
            elif isinstance(chunk, dict) and "content" in chunk:
                content_obj = chunk["content"]
                if isinstance(content_obj, str):
                    yield content_obj
                elif isinstance(content_obj, dict) and "content" in content_obj:
                    yield content_obj["content"]
    except Exception as e:
        logger.error(f"Error during agent execution: {e}")
        yield f"Error: {str(e)}"
