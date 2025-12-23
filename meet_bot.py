"""
Google Meet Bot - Step 1 Implementation
========================================
এই bot Google Meet এ join করবে এবং audio কে text এ convert করবে
"""

from playwright.sync_api import sync_playwright
import time
import speech_recognition as sr
import os

# ============================================
# CONFIGURATION (তোমার settings এখানে)
# ============================================

MEETING_LINK = "https://meet.google.com/oqq-rxku-acq"  # এখানে তোমার meet link দাও
BOT_NAME = "Dialogsy Bot"  # Bot এর নাম
RECORDING_DURATION = 60  # কত সেকেন্ড record করবে (60 = 1 minute)

# ============================================
# STEP 1: Browser খোলা এবং Meet এ যাওয়া
# ============================================

def join_google_meet(meeting_url):
    """
    এই function Google Meet এ bot কে join করায়
    
    কী করে:
    1. Chrome browser খোলে (headless না, তুমি দেখতে পাবে)
    2. Meeting link এ যায়
    3. Name set করে
    4. Mic/Camera permission দেয়
    5. Join button এ click করে
    """
    
    print("🚀 Bot starting...")
    print(f"📞 Meeting link: {meeting_url}")
    
    with sync_playwright() as p:
        # ============================================
        # Browser launch করা
        # ============================================
        
        # headless=False মানে browser window দেখা যাবে
        # তুমি যদি background এ run করতে চাও তাহলে headless=True দাও
        browser = p.chromium.launch(
            headless=False,  # False = browser দেখবে, True = background
            args=[
                '--use-fake-ui-for-media-stream',  # Auto allow mic/camera
                '--use-fake-device-for-media-stream',  # Fake device use করবে
                '--disable-blink-features=AutomationControlled'  # Bot detection এড়ানোর জন্য
            ]
        )
        
        # ============================================
        # New browser context (নতুন tab এর মতো)
        # ============================================
        
        # Microphone এবং camera permission দিয়ে দিচ্ছি
        context = browser.new_context(
            permissions=['microphone', 'camera'],
            viewport={'width': 1280, 'height': 720}
        )
        
        # ============================================
        # New page (tab) open করা
        # ============================================
        
        page = context.new_page()
        
        print("🌐 Opening Google Meet...")
        
        # Meeting link এ navigate করা
        page.goto(meeting_url, timeout=60000)  # 60 seconds timeout
        
        # Page load হওয়ার জন্য wait করা
        time.sleep(5)
        
        # ============================================
        # Bot এর নাম set করা
        # ============================================
        
        print(f"✍️ Setting name as: {BOT_NAME}")
        
        try:
            # Name input field খুঁজে বের করা
            # Google Meet এ name field এর selector হলো: input[placeholder="Your name"]
            name_input = page.locator('input[placeholder="Your name"]')
            
            # যদি name field থাকে তাহলে fill করা
            if name_input.count() > 0:
                name_input.fill(BOT_NAME)
                print("✅ Name set successfully")
        except Exception as e:
            print(f"⚠️ Name field not found (maybe already logged in): {e}")
        
        time.sleep(2)
        
        # ============================================
        # Mic/Camera control করা
        # ============================================
        
        print("🎤 Setting up mic and camera...")
        
        try:
            # Camera OFF করা
            # Google Meet এ camera button selector
            camera_button = page.locator('div[data-tooltip*="camera" i]')
            if camera_button.count() > 0:
                # যদি camera ON থাকে তাহলে OFF করা
                button_state = camera_button.get_attribute('data-is-muted')
                if button_state == 'false':
                    camera_button.click()
                    print("📷 Camera turned OFF")
            
            # Microphone ON রাখা
            # Mic button selector
            mic_button = page.locator('div[data-tooltip*="microphone" i]')
            if mic_button.count() > 0:
                button_state = mic_button.get_attribute('data-is-muted')
                if button_state == 'true':
                    mic_button.click()
                    print("🎤 Microphone turned ON")
        except Exception as e:
            print(f"⚠️ Could not control mic/camera: {e}")
        
        time.sleep(2)
        
        # ============================================
        # "Join now" button এ click করা
        # ============================================
        
        print("🚪 Attempting to join meeting...")
        
        try:
            # "Join now" বা "Ask to join" button খুঁজছি
            # Different possible button texts
            join_selectors = [
                'button:has-text("Join now")',
                'button:has-text("Ask to join")',
                'button:has-text("জয়েন")',  # Bangla
                'span:has-text("Join now")'
            ]
            
            for selector in join_selectors:
                join_button = page.locator(selector)
                if join_button.count() > 0:
                    join_button.click()
                    print("✅ Successfully clicked join button!")
                    break
        except Exception as e:
            print(f"❌ Could not find join button: {e}")
            print("Manual action required: Please click join button manually")
        
        # ============================================
        # Host approval এর জন্য wait করা
        # ============================================
        
        print("⏳ Waiting for host approval (30 seconds)...")
        time.sleep(30)  # Host approve করার জন্য যথেষ্ট সময়
        
        # ============================================
        # Meeting এ আছি কিনা verify করা
        # ============================================
        
        print("🔍 Checking if joined successfully...")
        
        # Check করছি waiting room এ আছি কিনা
        try:
            waiting_text = page.locator('text=/waiting for|asking to join/i')
            if waiting_text.count() > 0:
                print("⏳ Bot is in waiting room, waiting for host approval...")
                print("👉 Please click 'Admit' button in your meeting to let the bot join!")
                
                # 60 seconds পর্যন্ত wait করবো approval এর জন্য
                for i in range(12):  # 12 x 5 seconds = 60 seconds
                    time.sleep(5)
                    # Check করছি meeting এ ঢুকেছি কিনা
                    meeting_controls = page.locator('div[data-tooltip*="Turn off microphone"]')
                    if meeting_controls.count() > 0:
                        print("✅ Host approved! Joined successfully!")
                        break
                    print(f"⏳ Still waiting... ({(i+1)*5} seconds elapsed)")
        except:
            pass
        
        # Meeting এর elements আছে কিনা check করা
        in_meeting = False
        try:
            # Meeting controls (mic, camera buttons) আছে কিনা দেখছি
            meeting_controls = page.locator('div[data-tooltip*="Turn off microphone"]')
            if meeting_controls.count() > 0:
                in_meeting = True
                print("✅ Successfully joined the meeting!")
        except:
            print("⚠️ Could not verify meeting join status")
        
        # ============================================
        # Audio recording করা
        # ============================================
        
        if in_meeting:
            print(f"⏱️ Recording for {RECORDING_DURATION} seconds...")
            
            # এখানে তুমি audio recording logic add করবে
            # (পরের section এ দেখাচ্ছি)
            
            time.sleep(RECORDING_DURATION)
            
            print("🎬 Recording complete!")
        
        # ============================================
        # Meeting থেকে বের হওয়া
        # ============================================
        
        print("👋 Leaving meeting...")
        
        try:
            # "Leave call" button click করা
            leave_button = page.locator('button[aria-label*="Leave call"]')
            if leave_button.count() > 0:
                leave_button.click()
                print("✅ Left the meeting")
        except:
            print("⚠️ Could not find leave button")
        
        time.sleep(2)
        
        # Browser close করা
        browser.close()
        print("🏁 Bot stopped successfully")


# ============================================
# STEP 2: Audio Recording এবং Transcription
# ============================================

def record_and_transcribe():
    """
    এই function audio record করে এবং text এ convert করে
    
    ⚠️ NOTE: এটা একটা basic example
    Production এ তোমাকে proper audio capture করতে হবে
    """
    
    print("🎙️ Starting audio capture...")
    
    # Speech recognizer initialize করা
    recognizer = sr.Recognizer()
    
    # Microphone থেকে audio নেওয়া
    with sr.Microphone() as source:
        print("🔊 Listening...")
        
        # Background noise adjust করা
        recognizer.adjust_for_ambient_noise(source, duration=1)
        
        # Audio record করা (30 seconds)
        audio = recognizer.listen(source, timeout=30, phrase_time_limit=30)
        
        print("✅ Audio captured!")
    
    # ============================================
    # Speech to Text conversion
    # ============================================
    
    print("📝 Converting speech to text...")
    
    try:
        # Google Speech Recognition API use করছি (free)
        text = recognizer.recognize_google(audio, language='en-US')
        
        print(f"✅ Transcription complete!")
        print(f"📄 Text: {text}")
        
        # Text file এ save করা
        with open('output.txt', 'w', encoding='utf-8') as f:
            f.write(text)
        
        print("💾 Saved to output.txt")
        
        return text
        
    except sr.UnknownValueError:
        print("❌ Could not understand audio")
        return None
    except sr.RequestError as e:
        print(f"❌ API error: {e}")
        return None


# ============================================
# MAIN FUNCTION (এখান থেকে সব শুরু হয়)
# ============================================

def main():
    """
    Main entry point
    """
    print("=" * 50)
    print("🤖 DIALOGSY MEET BOT - STEP 1")
    print("=" * 50)
    print()
    
    # Step 1: Meeting এ join করা
    join_google_meet(MEETING_LINK)
    
    # Step 2: Audio transcribe করা (পরে করবো)
    # transcript = record_and_transcribe()


# ============================================
# Script run করা
# ============================================

if __name__ == "__main__":
    main()