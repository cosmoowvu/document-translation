"""
Test PaddleOCR service directly to verify coordinate conversion
"""
import requests

# Test file
test_file = r"D:\Project\backend\uploads\1268cf83-7a14-47de-ad25-5c92fc2b0376\original.pdf"

print("🧪 Testing PaddleOCR Service...")
print(f"   📄 File: {test_file}")

with open(test_file, 'rb') as f:
    files = {'file': ('test.pdf', f)}
    data = {'lang': 'en'}
    
    response = requests.post('http://localhost:8001/process', files=files, data=data, timeout=120)

if response.status_code == 200:
    result = response.json()
    print(f"\n✅ Success! Response keys: {result.keys()}")
    print(f"   📊 Pages: {result['num_pages']}")
    print(f"   🔧 OCR Engine: {result['ocr_engine']}")
    
    # Check first page
    if result['pages']:
        page_key = list(result['pages'].keys())[0]
        page_data = result['pages'][page_key]
        
        print(f"\n📄 Page {page_key}:")
        print(f"   Dimensions: {page_data['width']:.1f} x {page_data['height']:.1f}")
        print(f"   Blocks: {len(page_data['blocks'])}")
        
        # Show first block
        if page_data['blocks']:
            block = page_data['blocks'][0]
            bbox = block['bbox']
            print(f"\n📝 First Block:")
            print(f"   Text: {block['text'][:50]}...")
            print(f"   BBox: ({bbox['x1']:.1f}, {bbox['y1']:.1f}) -> ({bbox['x2']:.1f}, {bbox['y2']:.1f})")
            print(f"   Size: {bbox['x2']-bbox['x1']:.1f} x {bbox['y2']-bbox['y1']:.1f}")
            
            # Validate coordinates
            if bbox['x2'] > page_data['width'] or bbox['y2'] > page_data['height']:
                print(f"\n❌ ERROR: Coordinates exceed page dimensions!")
                print(f"   x2={bbox['x2']:.1f} > width={page_data['width']:.1f}")
                print(f"   y2={bbox['y2']:.1f} > height={page_data['height']:.1f}")
            else:
                print(f"\n✅ Coordinates look correct (within page bounds)")
else:
    print(f"❌ Error: {response.status_code}")
    print(response.text)
