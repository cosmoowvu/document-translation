"""
Ollama Model Management Utilities
Handles loading, unloading, and preloading models for optimal resource usage
"""
import requests
from typing import List

def get_loaded_models(ollama_url: str) -> List[str]:
    """Get list of currently loaded models"""
    try:
        base_url = ollama_url.replace('/api/generate', '')
        resp = requests.get(f"{base_url}/api/tags", timeout=10)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            return [m["name"] for m in models]
    except Exception as e:
        print(f"   ⚠️ Failed to get loaded models: {e}")
    return []


def unload_model(model_name: str, ollama_url: str) -> bool:
    """
    Unload a model from memory
    Uses keep_alive=0 to immediately free resources
    """
    try:
        # Ensure we use /api/generate endpoint
        if '/api/generate' not in ollama_url:
            base_url = ollama_url.rstrip('/')
            api_url = f"{base_url}/api/generate"
        else:
            api_url = ollama_url
            
        resp = requests.post(
            api_url,
            json={
                "model": model_name,
                "prompt": "",
                "keep_alive": 0
            },
            timeout=10
        )
        print(f"   🔄 Unloaded model: {model_name}")
        return True
    except Exception as e:
        print(f"   ⚠️ Failed to unload {model_name}: {e}")
        return False


def load_model(model_name: str, ollama_url: str, keep_alive: str = "5m") -> bool:
    """
    Preload a model into memory
    
    Args:
        model_name: Name of the model to load
        ollama_url: Ollama API endpoint
        keep_alive: How long to keep model loaded (e.g., "5m", "1h")
    
    Returns:
        True if successfully loaded, False otherwise
    """
    try:
        # Ensure we use /api/generate endpoint
        if '/api/generate' not in ollama_url:
            base_url = ollama_url.rstrip('/')
            api_url = f"{base_url}/api/generate"
        else:
            api_url = ollama_url
            
        print(f"   ⏳ Loading model: {model_name}...")
        resp = requests.post(
            api_url,
            json={
                "model": model_name,
                "prompt": "preload",
                "keep_alive": keep_alive
            },
            timeout=180
        )
        if resp.status_code == 200:
            print(f"   ✅ Model loaded: {model_name}")
            return True
        else:
            print(f"   ⚠️ Failed to load {model_name}: {resp.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Error loading {model_name}: {e}")
        return False


def preload_model(model_name: str, ollama_url: str) -> bool:
    """
    Preload a model for future use (keep loaded for longer duration)
    Useful for warming up models after job completion
    """
    return load_model(model_name, ollama_url, keep_alive="10m")
