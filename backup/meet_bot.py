"""
Dialogsy Meet Bot - Enhanced Version
====================================
এই bot Google Meet এ join করবে এবং meeting শেষ না হওয়া পর্যন্ত থাকবে
Real-time audio transcription করবে
"""

from playwright.sync_api import sync_playwright
import time
import threading
import pyaudio
import wave
import speech_recognition as sr
from datetime import datetime
import os

# ============================================
# CONFIGURATION
# ============================================

MEETING_LINK = "https://meet.google.com/cko-gupy-pem"  # তোমার meeting link
BOT_NAME = "Meeting Bot"
OUTPUT_FOLDER = "transcripts"  # Transcript save হবে এই folder এ

# Recording settings
CHUNK = 1024  # Audio chunk size
FORMAT = pyaudio.paInt16
CHANNELS = 2
RATE = 44100
RECORD_SECONDS = 5  # প্রতি 5 সেকেন্ডে একটা chunk transcribe করবে

# ============================================
# Create output folder
# ============================================

if not os.path.exists(OUTPUT_FOLDER):
    os.makedirs(OUTPUT_FOLDER)
    print(f"📁 Created folder: {OUTPUT_FOLDER}")

# ============================================
# Global variables
# ============================================

is_recording = False
audio_thread = None

# ============================================
# Audio Recording এবং Transcription
# ============================================

def continuous_audio_transcribe():
    """
    Background thread যেটা continuously audio record এবং transcribe করবে
    """
    global is_recording
    
    recognizer = sr.Recognizer()
    transcript_file = os.path.join(OUTPUT_FOLDER, f"transcript_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    
    print(f"📝 Transcript will be saved to: {transcript_file}")
    
    # Create/open transcript file
    with open(transcript_file, 'w', encoding='utf-8') as f:
        f.write(f"Meeting Transcript - Started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 70 + "\n\n")
    
    while is_recording:
        try:
            # Microphone থেকে audio capture
            with sr.Microphone() as source:
                print("🎤 Listening...")
                
                # Ambient noise adjust
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                
                # Audio record (5 seconds chunk)
                audio = recognizer.listen(source, timeout=5, phrase_time_limit=5)
                
                print("📝 Transcribing...")
                
                try:
                    # Google Speech Recognition (free)
                    text = recognizer.recognize_google(audio, language='en-US')
                    
                    if text.strip():  # যদি কিছু text পাওয়া যায়
                        timestamp = datetime.now().strftime('%H:%M:%S')
                        output = f"[{timestamp}] {text}\n"
                        
                        print(f"✅ {output.strip()}")
                        
                        # File এ save করা
                        with open(transcript_file, 'a', encoding='utf-8') as f:
                            f.write(output)
                
                except sr.UnknownValueError:
                    # কোন speech detect হয়নি (silence বা noise)
                    pass
                except sr.RequestError as e:
                    print(f"⚠️ API Error: {e}")
                    time.sleep(2)
        
        except Exception as e:
            print(f"⚠️ Audio capture error: {e}")
            time.sleep(1)
    
    print("🎤 Audio transcription stopped")

# ============================================
# Meeting Join করা (Enhanced)
# ============================================

def join_google_meet_persistent(meeting_url):
    """
    Meeting এ join করবে এবং meeting শেষ না হওয়া পর্যন্ত থাকবে
    """
    global is_recording, audio_thread
    
    print("=" * 70)
    print("🤖 DIALOGSY MEET BOT - STARTING")
    print("=" * 70)
    print(f"📞 Meeting Link: {meeting_url}")
    print(f"🤖 Bot Name: {BOT_NAME}")
    print()
    print("💡 TIP: Press Ctrl+C to stop the bot and leave meeting")
    print("=" * 70)
    print()
    
    with sync_playwright() as p:
        # ============================================
        # Browser Launch
        # ============================================
        
        print("🌐 Launching browser...")
        
        browser = p.chromium.launch(
            headless=False,
            args=[
                '--use-fake-ui-for-media-stream',
                '--use-fake-device-for-media-stream',
                '--disable-blink-features=AutomationControlled',
                '--autoplay-policy=no-user-gesture-required'
            ]
        )
        
        context = browser.new_context(
            permissions=['microphone', 'camera'],
            viewport={'width': 1280, 'height': 720}
        )
        
        page = context.new_page()
        
        # ============================================
        # Navigate to Meeting
        # ============================================
        
        print("📍 Navigating to meeting...")
        page.goto(meeting_url, timeout=60000)
        time.sleep(5)
        
        # ============================================
        # Set Name
        # ============================================
        
        print(f"✍️ Setting name: {BOT_NAME}")
        
        try:
            name_input = page.locator('input[placeholder="Your name"]')
            if name_input.count() > 0:
                name_input.fill(BOT_NAME)
                print("✅ Name set")
        except Exception as e:
            print(f"⚠️ Name field not found: {e}")
        
        time.sleep(2)
        
        # ============================================
        # Control Camera/Mic
        # ============================================
        
        print("🎛️ Setting up camera and microphone...")
        
        try:
            # Camera OFF
            camera_buttons = page.locator('button[aria-label*="camera" i], div[aria-label*="camera" i]')
            for i in range(camera_buttons.count()):
                try:
                    button = camera_buttons.nth(i)
                    aria_label = button.get_attribute('aria-label') or ''
                    if 'turn off' in aria_label.lower():
                        button.click()
                        print("📷 Camera turned OFF")
                        break
                except:
                    pass
            
            time.sleep(1)
            
            # Mic ON রাখা
            mic_buttons = page.locator('button[aria-label*="microphone" i], div[aria-label*="microphone" i]')
            for i in range(mic_buttons.count()):
                try:
                    button = mic_buttons.nth(i)
                    aria_label = button.get_attribute('aria-label') or ''
                    if 'turn on' in aria_label.lower():
                        button.click()
                        print("🎤 Microphone turned ON")
                        break
                except:
                    pass
        
        except Exception as e:
            print(f"⚠️ Camera/Mic control error: {e}")
        
        time.sleep(2)
        
        # ============================================
        # Join Meeting
        # ============================================
        
        print("🚪 Joining meeting...")
        
        join_clicked = False
        join_selectors = [
            'button:has-text("Join now")',
            'button:has-text("Ask to join")',
            'span:has-text("Join now")',
            'div[role="button"]:has-text("Join")'
        ]
        
        for selector in join_selectors:
            try:
                buttons = page.locator(selector)
                if buttons.count() > 0:
                    buttons.first.click()
                    print("✅ Join button clicked!")
                    join_clicked = True
                    break
            except:
                continue
        
        if not join_clicked:
            print("⚠️ Could not find join button automatically")
            print("👉 Please click the join button manually")
        
        # ============================================
        # Wait for approval / Join confirmation
        # ============================================
        
        print("⏳ Waiting for meeting join confirmation...")
        
        max_wait = 60  # 60 seconds wait করবো
        joined = False
        
        for i in range(max_wait):
            time.sleep(1)
            
            # Check if we're in the meeting
            try:
                # Meeting controls visible থাকলে বুঝবো join হয়েছে
                meeting_indicators = [
                    'button[aria-label*="Leave call"]',
                    'button[aria-label*="Turn off microphone"]',
                    'div[data-meeting-title]'
                ]
                
                for indicator in meeting_indicators:
                    if page.locator(indicator).count() > 0:
                        joined = True
                        break
                
                if joined:
                    print()
                    print("✅ Successfully joined the meeting!")
                    print()
                    break
                
                # Progress indicator
                if (i + 1) % 10 == 0:
                    print(f"⏳ Still waiting... ({i + 1}s elapsed)")
            
            except:
                continue
        
        if not joined:
            print("⚠️ Could not confirm meeting join")
            print("⚠️ Assuming joined, continuing anyway...")
        
        # ============================================
        # Start Audio Transcription
        # ============================================
        
        print("=" * 70)
        print("🎙️ STARTING AUDIO TRANSCRIPTION")
        print("=" * 70)
        print()
        
        is_recording = True
        audio_thread = threading.Thread(target=continuous_audio_transcribe, daemon=True)
        audio_thread.start()
        
        # ============================================
        # Keep Bot in Meeting (Until Ctrl+C)
        # ============================================
        
        print("🤖 Bot is now in the meeting!")
        print("📝 Transcribing audio in real-time...")
        print()
        print("💡 Press Ctrl+C to stop the bot and leave the meeting")
        print("=" * 70)
        print()
        
        try:
            # Infinite loop - meeting চলতে থাকবে
            while True:
                # Check if meeting is still active
                try:
                    leave_button = page.locator('button[aria-label*="Leave call"]')
                    if leave_button.count() == 0:
                        print("⚠️ Meeting seems to have ended")
                        break
                except:
                    pass
                
                # Keep page alive
                time.sleep(10)
        
        except KeyboardInterrupt:
            print()
            print("⚠️ Ctrl+C detected - Stopping bot...")
        
        # ============================================
        # Cleanup - Leave Meeting
        # ============================================
        
        print()
        print("=" * 70)
        print("🛑 STOPPING BOT")
        print("=" * 70)
        
        # Stop audio recording
        is_recording = False
        if audio_thread:
            audio_thread.join(timeout=5)
        
        print("👋 Leaving meeting...")
        
        try:
            leave_button = page.locator('button[aria-label*="Leave call"]')
            if leave_button.count() > 0:
                leave_button.click()
                print("✅ Left the meeting")
                time.sleep(2)
        except:
            print("⚠️ Could not click leave button")
        
        # Close browser
        browser.close()
        
        print()
        print("=" * 70)
        print("🏁 BOT STOPPED SUCCESSFULLY")
        print(f"📁 Transcripts saved in: {OUTPUT_FOLDER}/")
        print("=" * 70)

# ============================================
# MAIN
# ============================================

def main():
    try:
        join_google_meet_persistent(MEETING_LINK)
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()