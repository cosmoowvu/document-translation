"""Test with a simple request to check if PaddleOCR debug logs appear"""
import requests
import json

url = "http://localhost:8001/process"

# Create a minimal test - just check if service responds with debug
print("Testing PaddleOCR service debug output...")
print("Check the PaddleOCR terminal for debug messages!")
print("\nSending request...")

try:
    # Use any small image file
    test_data = {'lang': 'en'}
    response = requests.get("http://localhost:8001/", timeout=5)
    print(f"Service is running: {response.status_code}")
except Exception as e:
    print(f"Error: {e}")
