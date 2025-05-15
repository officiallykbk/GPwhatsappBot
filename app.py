from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse 
import requests
import re
from io import BytesIO
from PIL import Image
import pyzbar.pyzbar as pyzbar
from dotenv import load_dotenv
import os

app = Flask(__name__)
GHANA_POST_API = "https://ghanapostgps.sperixlabs.org"
load_dotenv()

def create_response(message_body):
    """Create Twilio MessagingResponse with WhatsApp formatting"""
    resp = MessagingResponse()
    resp.message(message_body)
    return Response(str(resp), mimetype='application/xml')


def get_help_message():
    return create_response(
        """🚀 *GhanaPost GPS Bot Help* 🚀\n\n
        🔍 *Lookup Address*:\n
        Send a GhanaPost code like:\n
        • `GA1234567`\n
        • `GA-123-4567`\n\n
        📷 *Scan QR Code*:\n
        Send a GhanaPost QR image\n\n
        📍 *Share Location*:\n
        Tap 📎 → Location → Send"""
    )



def fetch_ghanapost_data(code):
    """Get address details from GhanaPost API"""
    payload = f'address={code}'
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    try:
        response = requests.post(GHANA_POST_API, headers=headers, data=payload, timeout=5)
        if response.status_code == 200:
            data = response.json().get('data', {}).get('Table', [{}])[0]
            return {
                'street': data.get('Street', 'N/A'),
                'district': data.get('District', 'N/A'),
                'region': data.get('Region', 'N/A'),
                'lat': data.get('CenterLatitude'),
                'lng': data.get('CenterLongitude'),
                'raw_code': code
            }
    except Exception as e:
        print(f"API Error: {str(e)}")
    return None

def reverse_geocode(lat, lng):
    """Get GhanaPost address from coordinates"""
    payload = {'lat': lat, 'long': lng}
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    
    try:
        response = requests.post(GHANA_POST_API, headers=headers, data=payload, timeout=5)
        return response.json().get('data', {}).get('gpscode') if response.ok else None
    except Exception as e:
        print(f"Reverse Geocode Error: {str(e)}")
        return None

def decode_qr(image_url):
    """Extract GhanaPost code from QR image with robust error handling"""
    try:
        # Your Twilio Account SID and Auth Token
        account_sid = os.getenv('TWILIO_SID')
        auth_token = os.getenv('TWILIO_AUTH_KEY')
        
        # Create session with authentication
        session = requests.Session()
        session.auth = (account_sid, auth_token)
        
        # Download image with timeout and auth
        response = session.get(image_url, timeout=5)
        response.raise_for_status()
        
        # Verify image content
        if not response.content:
            print("Empty image content received")
            return None
            
        try:
            img = Image.open(BytesIO(response.content))
            decoded = pyzbar.decode(img)
            
            if not decoded:
                print("No QR code detected in image")
                return None
                
            # Get first QR code content
            qr_text = decoded[0].data.decode('utf-8')
            print(f"QR decoded content: {qr_text}")
            return qr_text
            
        except Image.UnidentifiedImageError:
            print("Invalid image format received")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"Image download failed: {str(e)}")
    except Exception as e:
        print(f"Unexpected QR processing error: {str(e)}")
    return None

def extract_code_from_qr(qr_text):
    """Extract GhanaPost code from QR text with validation"""
    if not qr_text:
        return None
        
    # Clean text and find matches
    clean_text = qr_text.strip().upper()
    
    # Match formats: AK-325-9995 or GA1234567
    pattern = r'\b([A-Z]{2})(-?)(\d{3})\2(\d{3,4})\b'
    match = re.search(pattern, clean_text)
    
    if not match:
        print(f"No valid code found in QR text: {qr_text}")
        return None
        
    # Reconstruct standardized format
    code = f"{match.group(1)}-{match.group(3)}-{match.group(4)}"
    print(f"Extracted code: {code}")
    return code

@app.route('/whatsapp-webhook', methods=['POST'])
def handle_whatsapp():
    try:
        # Get incoming message data
        incoming_msg = request.values.get('Body', '').strip().upper()
        media_url = request.values.get('MediaUrl0')
        
        # Case 1: QR Code Processing
        if media_url:
            qr_content = decode_qr(media_url)
            if qr_content:
                ghanapost_code = extract_code_from_qr(qr_content)
                if not ghanapost_code:
                    return create_response("❌ No valid GhanaPost code found in QR image")
                
                data = fetch_ghanapost_data(ghanapost_code)
                if not data:
                    return create_response(f"❌ Address not found for code: {ghanapost_code}")
                
                return create_response(
                    f"📍 *Address Found* 📍\n"
                    f"➡️ Code: {data['raw_code']}\n"
                    f"➡️ Street: {data['street']}\n"
                    f"➡️ District: {data['district']}\n"
                    f"➡️ Region: {data['region']}\n\n"
                    f"🗺️ View on map: https://maps.google.com?q={data['lat']},{data['lng']}"
                )
            return create_response("❌ Could not read QR code. Please send a clear image of a GhanaPost QR code")

        # Case 2: GhanaPost Code Processing
        if re.match(r'^[A-Za-z]{2}[-]?\d{3}[-]?\d{3,4}$', incoming_msg):
            if data := fetch_ghanapost_data(incoming_msg):
                return create_response(
                    f"📍 *Address Found* 📍\n"
                    f"➡️ *Code*: {data['raw_code']}\n"
                    f"➡️ *Street*: {data['street']}\n"
                    f"➡️ *District*: {data['district']}\n"
                    f"➡️ *Region*: {data['region']}\n\n"
                    f"🗺️ View on map: https://maps.google.com?q={data['lat']},{data['lng']}"
                )
            return create_response("❌ Invalid GhanaPost code. Try GA1234567 or GA-123-4567")

        # Case 3: Location Shared
        if request.values.get('Latitude') and request.values.get('Longitude'):
            lat = float(request.values.get('Latitude'))
            lng = float(request.values.get('Longitude'))

            ghanapost_code = reverse_geocode(lat, lng)
            return create_response(
                f"📍 *Location Received* 📍\n"
                f"➡️ *Coordinates*: {lat:.6f}, {lng:.6f}\n"
                f"➡️ *GhanaPost Code*: {ghanapost_code or 'Not available'}\n\n"
                f"🗺️ View on map: https://maps.google.com?q={lat},{lng}"
            )

        # Default Help Message
        return get_help_message()

    except Exception as e:
        print(f"Handler Error: {str(e)}")
        return create_response("⚠️ Server error. Please try again later.")

if __name__ == '__main__':
    app.run(port=5000, debug=True)