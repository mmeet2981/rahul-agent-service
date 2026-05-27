import os
from .vllm import VLLM
from src.utils import logger
from .groq import GroqLLM
from .gemini import GeminiLLM

def get_primary_llm() -> VLLM | GroqLLM:
    """
    Returns the primary LLM instance (VLLM).
    """
    if os.environ.get("GEMINI_API_KEY"):
        return GeminiLLM(api_key=os.environ.get("GEMINI_API_KEY"), model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"))
    if os.environ.get("GROQ_API_KEY"):
        return GroqLLM(api_key=os.environ.get("GROQ_API_KEY"), model=os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"))
    vllm_host = os.environ.get("VLLM_HOST", "http://127.0.0.1:11434")
    model_name = os.environ.get("VLLM_MODEL", "Qwen/Qwen2.5-32B-Instruct-AWQ")
    
    logger.info(f"Initializing VLLM with model: {model_name} at {vllm_host}")
    return VLLM(model=model_name, base_url=vllm_host, logger=logger)
