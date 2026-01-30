
import os
import sys

print("--- ENVIRONMENT VARIABLES ---")
for key, value in os.environ.items():
    if "TYPHOON" in key or "URL" in key or "1143" in value:
        print(f"{key}: {value}")
print("--- END ---")

try:
    from typhoon_ocr import ocr_document, ocr_utils
    print(f"Typhoon package file: {ocr_utils.__file__}")
    # Inspect default arg of ocr_document
    import inspect
    sig = inspect.signature(ocr_document)
    base_url_param = sig.parameters['base_url']
    print(f"ocr_document base_url default: {base_url_param.default}")
except ImportError:
    print("Could not import typhoon_ocr")
except Exception as e:
    print(f"Error inspecting typhoon: {e}")
