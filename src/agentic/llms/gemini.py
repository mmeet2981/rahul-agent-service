from RAW.llms import BaseLLM
from RAW.utils import Logger
import httpx
from pydantic import BaseModel
from typing import List, Optional, Dict, Union, AsyncGenerator
from RAW.modals import LLMCapability, Message, Image, Tool, ToolCall
import json
import numpy as np
import re

logger = Logger("GeminiLLM")

class GeminiOptions(BaseModel):
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    max_output_tokens: Optional[int] = None
    stop_sequences: Optional[List[str]] = None

class GeminiLLM(BaseLLM):
    def __init__(self, api_key: str, model: str = "gemini-1.5-flash", options: Optional[GeminiOptions] = None):
        super().__init__()
        self.client = httpx.AsyncClient(
            base_url="https://generativelanguage.googleapis.com/v1beta",
            timeout=300.0
        )
        self.api_key = api_key
        self.model = model
        self.options = options
        self.capabilities: List[LLMCapability] = [LLMCapability.COMPLETION, LLMCapability.TOOLS]

    def _build_generation_config(self) -> Dict:
        """Build generation config from options"""
        config = {}
        if self.options:
            if self.options.temperature is not None:
                config["temperature"] = self.options.temperature
            if self.options.top_p is not None:
                config["topP"] = self.options.top_p
            if self.options.top_k is not None:
                config["topK"] = self.options.top_k
            if self.options.max_output_tokens is not None:
                config["maxOutputTokens"] = self.options.max_output_tokens
            if self.options.stop_sequences:
                config["stopSequences"] = self.options.stop_sequences
        return config

    async def generate(self, prompt: str, images: Optional[List[Image]] = None, schema: Optional[Union[str, Dict]] = None, stream: bool = False) -> Union[str, Dict, AsyncGenerator[Union[str, Dict], None]]:
        if not prompt:
            logger.warning("Prompt is empty.")

        parts = [{"text": prompt}]
        
        if images:
            for image in images:
                parts.append({
                    "inline_data": {
                        "mime_type": image.mime_type or "image/jpeg",
                        "data": image.to_base64().split(',')[-1]  
                    }
                })

        body = {
            "contents": [{"parts": parts}]
        }

       
        generation_config = self._build_generation_config()
        if generation_config:
            body["generationConfig"] = generation_config

        if schema:
            if not body.get("generationConfig"):
                body["generationConfig"] = {}
            body["generationConfig"]["responseMimeType"] = "application/json"
            if isinstance(schema, dict):
                body["generationConfig"]["responseSchema"] = schema

        if stream:
            return self._stream_response(body)
        else:
            return await self._get_direct_response(body)

    async def _get_direct_response(self, body: Dict) -> Union[str, Dict]:
        try:
            url = f"/models/{self.model}:generateContent?key={self.api_key}"
            
            response = await self.client.post(url, json=body)
            response.raise_for_status()
            data = response.json()
            
            if "candidates" in data and data["candidates"]:
                content = data["candidates"][0]["content"]["parts"][0]["text"]
                return content
            else:
                raise RuntimeError("No candidates in response")
                
        except httpx.HTTPStatusError as exc:
            error_text = exc.response.text if hasattr(exc.response, 'text') else str(exc)
            raise RuntimeError(f"HTTP error: {error_text}")
        except Exception as e:
            raise RuntimeError(f"Generation error: {str(e)}")

    async def _stream_response(self, body: Dict) -> AsyncGenerator[Union[str, Dict], None]:
        try:
            url = f"/models/{self.model}:streamGenerateContent?key={self.api_key}&alt=sse"
            
            try:
                async with self.client.stream("POST", url, json=body) as response:
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        await response.aread()
                        raise exc
                    
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                  
                        if line.startswith('data: '):
                            line = line[6:]  
                        if line == '[DONE]':
                            break
                            
                        try:
                            data = json.loads(line)
                            if "candidates" in data and data["candidates"]:
                                if "content" in data["candidates"][0]:
                                    parts = data["candidates"][0]["content"]["parts"]
                                    if parts and "text" in parts[0]:
                                        yield parts[0]["text"]
                        except json.JSONDecodeError:
                            continue
            except httpx.HTTPStatusError as exc:
                try:
                    await exc.response.aread()
                except Exception:
                    pass
                raise exc
                    
        except httpx.HTTPStatusError as exc:
            error_text = exc.response.text if hasattr(exc.response, 'text') else str(exc)
            raise RuntimeError(f"HTTP error: {error_text}")
        except Exception as e:
            raise RuntimeError(f"Stream error: {str(e)}")

    def _convert_message_to_gemini_format(self, message: Message, prev_messages: Optional[List[Message]] = None) -> Dict:
        """Convert Message to Gemini format"""
        role_mapping = {
            "user": "user",
            "assistant": "model",
            "system": "user",
            "tool": "function"
        }
        
        parts = []
        if message.content:
            parts.append({"text": message.content})
            
        if message.images:
            for image in message.images:
                parts.append({
                    "inline_data": {
                        "mime_type": image.mime_type or "image/jpeg",
                        "data": image.to_base64().split(',')[-1]
                    }
                })
        
        if message.tool_calls:
            for tool_call in message.tool_calls:
                parts.append({
                    "functionCall": {
                        "name": tool_call.name,
                        "args": tool_call.arguments
                    }
                })
        
        if message.role == "tool":
            # For role 'function', return a function response
            function_name = None
            if prev_messages:
                for prev_msg in reversed(prev_messages):
                    if prev_msg.role == "assistant" and prev_msg.tool_calls:
                        if hasattr(message, "tool_call_id") and message.tool_call_id:
                            matching_call = next((tc for tc in prev_msg.tool_calls if tc.id == message.tool_call_id), None)
                            if matching_call:
                                function_name = matching_call.name
                                break
                        function_name = prev_msg.tool_calls[-1].name
                        break
            if not function_name:
                function_name = "unknown_function"
            
            # Sanitize name to match sanitized declaration if needed
            if not function_name or not re.match(r'^[a-zA-Z_][a-zA-Z0-9_\.\-]*$', function_name) or len(function_name) > 64:
                function_name = re.sub(r'[^a-zA-Z0-9_\.\-]', '', function_name)[:64]
                
            parts = [{
                "functionResponse": {
                    "name": function_name,
                    "response": {"content": message.content}
                }
            }]
        
        return {
            "role": role_mapping.get(message.role, "user"),
            "parts": parts
        }
    
    
    def _convert_tool_to_gemini_format(self, tool: Tool) -> Dict:
        """Convert Tool to Gemini format with name sanitization"""
        try:
            name = tool.name
            # Sanitize function name to meet Gemini API requirements
            if not name or not re.match(r'^[a-zA-Z_][a-zA-Z0-9_\.\-]*$', name) or len(name) > 64:
                name = f"_{name}" if name else "tool_function"
                name = re.sub(r'[^a-zA-Z0-9_\.\-]', '', name)[:64]
            return {
                "name": name,
                "description": tool.description or "",
                "parameters": {
                    "type": "object",
                    "properties": {
                        param.name: {
                            "type": param.type,
                            "description": param.description or ""
                        }
                        for param in tool.parameters
                    },
                    "required": [
                        param.name for param in tool.parameters if param.required
                    ]
                }
            }
        except Exception as e:
            raise ValueError(f"Tool conversion error for {tool.name}: {str(e)}")

    async def chat(self, messages: List[Message], schema: Optional[str] = None, stream: bool = False, tools: List[Tool] = []) -> Union[Message, AsyncGenerator[Message, None]]:
        if not messages:
            logger.warning("Messages list is empty.")

       
        contents = []
        for i, msg in enumerate(messages):
            contents.append(self._convert_message_to_gemini_format(msg, prev_messages=messages[:i]))

        body = {
            "contents": contents
        }

       
        generation_config = self._build_generation_config()
        if generation_config:
            body["generationConfig"] = generation_config

        
        if tools and LLMCapability.TOOLS in self.capabilities:
            body["tools"] = [{
                "functionDeclarations": [self._convert_tool_to_gemini_format(tool) for tool in tools]
            }]

        if schema:
            if not body.get("generationConfig"):
                body["generationConfig"] = {}
            body["generationConfig"]["responseMimeType"] = "application/json"
            if isinstance(schema, dict):
                body["generationConfig"]["responseSchema"] = schema

        if stream:
            return self._stream_chat_response(body)
        else:
            return await self._get_direct_chat_response(body)

    async def _get_direct_chat_response(self, body: Dict) -> Message:
        try:
            url = f"/models/{self.model}:generateContent?key={self.api_key}"
            
            response = await self.client.post(url, json=body)
            response.raise_for_status()
            data = response.json()
            
            if "candidates" in data and data["candidates"]:
                candidate = data["candidates"][0]
                content_data = candidate["content"]
                
                content = ""
                tool_calls = []
                
                for part in content_data["parts"]:
                    if "text" in part:
                        content += part["text"]
                    elif "functionCall" in part:
                        func_call = part["functionCall"]
                        tool_call = ToolCall(
                            name=func_call["name"],
                            arguments=func_call.get("args", {})
                        )
                        tool_calls.append(tool_call)
                
                return Message(
                    role="assistant",
                    content=content,
                    images=[],
                    tool_calls=tool_calls
                )
            else:
                raise RuntimeError("No candidates in response")
                
        except httpx.HTTPStatusError as exc:
            error_text = exc.response.text if hasattr(exc.response, 'text') else str(exc)
            logger.warning(f"HTTP error in chat response: {error_text}")
            raise RuntimeError(f"HTTP error: {error_text}")
        except Exception as e:
            logger.warning(f"Chat error: {str(e)}")
            raise RuntimeError(f"Chat error: {str(e)}")
        
    async def _stream_chat_response(self, body: Dict) -> AsyncGenerator[Message, None]:
            try:
                url = f"/models/{self.model}:streamGenerateContent?key={self.api_key}&alt=sse"
                
                try:
                    async with self.client.stream("POST", url, json=body) as response:
                        try:
                            response.raise_for_status()
                        except httpx.HTTPStatusError as exc:
                            await response.aread()
                            raise exc
                        
                        async for line in response.aiter_lines():
                            line = line.strip()
                            if not line:
                                continue
                                
                            if line.startswith('data: '):
                                line = line[6:]
                            
                            if line == '[DONE]':
                                break
                                
                            try:
                                data = json.loads(line)
                                if "candidates" in data and data["candidates"]:
                                    candidate = data["candidates"][0]
                                    logger.info(f"candidate: {candidate}")
                                    if "content" in candidate:
                                        content_data = candidate["content"]
                                        
                                        content = ""
                                        tool_calls = []
                                        logger.info(f"content_data: {content_data}")
                                        
                                        # --- FIX: Safely extract 'parts' ---
                                        parts = content_data.get("parts", [])
                                        
                                        for part in parts:
                                            if "text" in part:
                                                content += part["text"]
                                            elif "functionCall" in part:
                                                func_call = part["functionCall"]
                                                tool_call = ToolCall(
                                                    name=func_call["name"],
                                                    arguments=func_call.get("args", {})
                                                )
                                                tool_calls.append(tool_call)
                                        
                                        # Only yield if we actually have text or tool calls to avoid sending empty messages
                                        if content or tool_calls:
                                            message = Message(
                                                role="assistant",
                                                content=content,
                                                images=[],
                                                tool_calls=tool_calls
                                            )
                                            yield message
                                        
                            except json.JSONDecodeError:
                                continue
                except httpx.HTTPStatusError as exc:
                    try:
                        await exc.response.aread()
                    except Exception:
                        pass
                    raise exc
                            
            except httpx.HTTPStatusError as exc:
                error_text = exc.response.text if hasattr(exc.response, 'text') else str(exc)
                logger.warning(f"HTTP error in stream chat response: {error_text}")
                raise RuntimeError(f"HTTP error: {error_text}")
            except Exception as e:
                logger.warning(f"Stream chat error: {str(e)}")
                raise RuntimeError(f"Stream error: {str(e)}")
    async def stop(self):
        await self.client.aclose()

    def _del_(self):
        pass

    def __del__(self):
        pass

    async def embed(self, text: str) -> np.ndarray:
        raise NotImplementedError("GeminiLLM does not support embedding.")