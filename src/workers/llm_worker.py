import asyncio
import logging
import os
from src.utils.redis import claim_job, update_state, append_chunk, get_message_state
from src.services.message_service import MessageService
from src.models.messages import MessageUpdate
from dotenv import load_dotenv
import httpx

load_dotenv()

from src.utils import logger
import json

async def process_job(payload_data):
    # If your claim_job returns a string/JSON, parse it
    if isinstance(payload_data, str):
        data = json.loads(payload_data)
    else:
        data = payload_data

    message_id = data.get("message_id")
    message_type = data.get("message_type", "default") # 'whatsapp' or 'default'

    logger.info(f"Processing {message_type} message {message_id}")
    
    try:
        await update_state(message_id, "processing", message_type=message_type)
        
        # 1. Fetch Message using specific service
        if message_type == "whatsapp":
            from src.services.whatsapp_service import WhatsAppService
            assistant_msg = WhatsAppService.get_message(message_id)
            print(f"Assistantaas message {assistant_msg}")
        elif message_type == "email":
            from src.services.email_service import EmailService
            assistant_msg = EmailService.get_message(message_id)
        else:
            from src.services.message_service import MessageService
            assistant_msg = MessageService.get_message(message_id)

        if not assistant_msg:
            logger.error(f"Message {message_id} of type {message_type} not found")
            return

        # 2. Invoke Agent (Pass message_type down)
        from src.utils.invoke_agent import invoke_agent
        
        response_text = ""
        async for chunk in invoke_agent(assistant_msg.conversation_id, message_id, message_type):
            await append_chunk(message_id, chunk, message_type=message_type)
            response_text += chunk
    
        # Finalize & Persist
        await update_state(message_id, "done", message_type=message_type)
        
        update_data = MessageUpdate(content=response_text.strip(), metadata={"processed": True})
        
        if message_type == "whatsapp":
                
            node_api_url = f"{os.getenv('WHATSAPP_HOST', 'http://127.0.0.1:8080')}/send" 
            recipient_id = assistant_msg.from_number
            

            logger.info(f"Sending response to recipient: {recipient_id}")
            
            async with httpx.AsyncClient() as client:
                try:
                    payload = {
                        "number": recipient_id, 
                        "message": response_text.strip() or "None",
                        "conversation_id": assistant_msg.conversation_id,
                        "group_id": assistant_msg.group_id
                    }
                    logger.info(f"Payload to Node: {payload}")
                    await client.post(node_api_url, json=payload)
                except Exception as e:
                    logger.error(f"Failed to notify Node service: {e}")
        elif message_type == "email":
            # Send response via email service
            email_host = os.getenv(
                "EMAIL_HOST",
                f"http://127.0.0.1:{os.getenv('EMAIL_SERVICE_PORT', '3001')}"
            )
            node_api_url = f"{email_host}/send"
            recipient_email = assistant_msg.sender_email
            
            logger.info(f"Sending email response to: {recipient_email}")
            
            # Use conversation title as fallback for subject if email subject is missing or generic
            email_subject = assistant_msg.subject
            if not email_subject or email_subject in ["No Subject", "None", "null", "undefined"]:
                from src.services.conversation_service import ConversationService
                conv = ConversationService.get_conversation(assistant_msg.conversation_id)
                if conv:
                    # Prefer conversation title if it's set and not generic
                    if conv.title and conv.title not in ["No Subject", "None", "null", "undefined"]:
                        email_subject = conv.title
                    elif conv.agent:
                        # Fallback to agent name (e.g. "DatabaseAgent" -> "Database Agent")
                        import re
                        email_subject = re.sub(r'([a-z])([A-Z])', r'\1 \2', conv.agent).strip()
            
            if not email_subject or email_subject in ["None", "null", "undefined"]:
                email_subject = "Assistant Update"

            async with httpx.AsyncClient() as client:
                try:
                    original_subject = email_subject
                    if not original_subject.lower().startswith("re:"):
                        subject = f"Re: {original_subject}"
                    else:
                        subject = original_subject
                        
                    # For emails, we want to ensure we only send the acknowledgment if specified.
                    # The prompt already instructs the agent to only give acknowledgment.
                    # We send the full response_text which should now be just the acknowledgment.
                    payload = {
                        "to": recipient_email,
                        "subject": subject,
                        "text": response_text.strip(),
                        "thread_id": assistant_msg.thread_id
                    }
                    await client.post(node_api_url, json=payload)
                except Exception as e:
                    logger.error(f"Failed to send email via Node service: {e}")
        else:
            MessageService.update_message(message_id, update_data)

    except Exception as e:
        logger.error(f"Error processing message {message_id}: {e}")
        await update_state(message_id, "error", message_type=message_type, error=str(e))

async def main():
    logger.info("Starting LLM Worker...")
    while True:
        try:
            message_id = await claim_job()
            
            if message_id:
                asyncio.create_task(process_job(message_id))
            else:
                # Wait a bit before polling again
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Worker loop error: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
