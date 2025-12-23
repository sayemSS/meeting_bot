from playwright.sync_api import sync_playwright
import time
import threading
import speech_recognition as sr
from datetime import datetime
import os
import sys


BOT_NAME = "Test Bot"
OUTPUT_FOLDER = "transcripts"
RECORD_CHUNK_SECONDS = 5


if not os.path.exists(OUTPUT_FOLDER):
    os.makedirs(OUTPUT_FOLDER)

is_recording = False
audio_thread = None


def transcribe_audio():
    global is_recording
    
    recognizer = sr.Recognizer()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    transcript_file = os.path.join(OUTPUT_FOLDER, f"transcript_{timestamp}.txt")
    
    with open(transcript_file, 'w', encoding='utf-8') as f:
        f.write(f"Meeting Transcript - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 70 + "\n\n")
    
    print(f"Transcript: {transcript_file}")
    
    while is_recording:
        try:
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = recognizer.listen(source, timeout=RECORD_CHUNK_SECONDS, 
                                        phrase_time_limit=RECORD_CHUNK_SECONDS)
                
                try:
                    text = recognizer.recognize_google(audio, language='en-US')
                    
                    if text.strip():
                        time_str = datetime.now().strftime('%H:%M:%S')
                        output = f"[{time_str}] {text}\n"
                        print(output.strip())
                        
                        with open(transcript_file, 'a', encoding='utf-8') as f:
                            f.write(output)
                
                except sr.UnknownValueError:
                    pass
                except sr.RequestError as e:
                    print(f"API Error: {e}")
                    time.sleep(2)
        
        except Exception as e:
            print(f"Audio Error: {e}")
            time.sleep(1)


def join_meeting(meeting_url):
    global is_recording, audio_thread
    
    print("\n" + "="*70)
    print("Google Meet Bot")
    print("="*70)
    print(f"Meeting: {meeting_url}")
    print(f"Bot Name: {BOT_NAME}")
    print("Press Ctrl+C to stop")
    print("="*70 + "\n")
    
    with sync_playwright() as p:
        
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
        
        print("Opening meeting...")
        page.goto(meeting_url, timeout=60000)
        time.sleep(5)
        
        # Set bot name
        try:
            name_input = page.locator('input[placeholder="Your name"]')
            if name_input.count() > 0:
                name_input.fill(BOT_NAME)
        except:
            pass
        
        time.sleep(2)
        
        # Turn OFF camera (ensure it's off)
        print("Turning off camera...")
        try:
            # Try multiple selectors for camera button
            camera_selectors = [
                'button[aria-label*="Turn off camera" i]',
                'button[aria-label*="camera" i]',
                'div[aria-label*="Turn off camera" i]',
                'div[data-tooltip*="Turn off camera" i]'
            ]
            
            camera_turned_off = False
            for selector in camera_selectors:
                try:
                    buttons = page.locator(selector)
                    for i in range(buttons.count()):
                        button = buttons.nth(i)
                        aria_label = button.get_attribute('aria-label') or ''
                        
                        # If camera is ON, turn it OFF
                        if 'turn off' in aria_label.lower() and 'camera' in aria_label.lower():
                            button.click()
                            print("Camera turned OFF")
                            camera_turned_off = True
                            break
                    
                    if camera_turned_off:
                        break
                except:
                    continue
            
            # Double check camera is off
            if not camera_turned_off:
                print("Camera already OFF or couldn't toggle")
        
        except Exception as e:
            print(f"Camera control warning: {e}")
        
        time.sleep(2)
        
        # Join meeting
        print("Joining meeting...")
        
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
                    break
            except:
                continue
        
        # Wait for join confirmation
        print("Waiting for confirmation...")
        
        joined = False
        for i in range(60):
            time.sleep(1)
            
            try:
                meeting_indicators = [
                    'button[aria-label*="Leave call"]',
                    'button[aria-label*="Turn off microphone"]'
                ]
                
                for indicator in meeting_indicators:
                    if page.locator(indicator).count() > 0:
                        joined = True
                        break
                
                if joined:
                    print("Joined successfully!\n")
                    break
            except:
                continue
        
        if not joined:
            print("Could not confirm join, continuing anyway...\n")
        
        # Start transcription
        print("Starting transcription...")
        print("-"*70 + "\n")
        
        is_recording = True
        audio_thread = threading.Thread(target=transcribe_audio, daemon=True)
        audio_thread.start()
        
        # Keep bot in meeting and monitor if meeting ends
        print("Bot is active. Monitoring meeting status...\n")
        
        try:
            meeting_ended = False
            check_interval = 5  # Check every 5 seconds
            
            while True:
                try:
                    # Check if "Leave call" button exists
                    leave_button = page.locator('button[aria-label*="Leave call"]')
                    
                    if leave_button.count() == 0:
                        # Button disappeared, meeting likely ended
                        meeting_ended = True
                        print("\n" + "="*70)
                        print("Meeting has ended (host closed the meeting)")
                        print("="*70)
                        break
                    
                    # Check if we're on a different page (kicked out, etc)
                    current_url = page.url
                    if "meet.google.com" not in current_url:
                        meeting_ended = True
                        print("\n" + "="*70)
                        print("Left the meeting (redirected)")
                        print("="*70)
                        break
                    
                    # Check for "You left the meeting" or similar messages
                    left_messages = page.locator('text=/You left|meeting ended|has ended/i')
                    if left_messages.count() > 0:
                        meeting_ended = True
                        print("\n" + "="*70)
                        print("Meeting ended or you were removed")
                        print("="*70)
                        break
                
                except Exception as e:
                    # If we get errors checking, meeting might have ended
                    print(f"\nError checking meeting status: {e}")
                    meeting_ended = True
                    break
                
                time.sleep(check_interval)
        
        except KeyboardInterrupt:
            print("\n\nStopping bot (Ctrl+C pressed)...")
        
        # Cleanup
        is_recording = False
        if audio_thread:
            audio_thread.join(timeout=5)
        
        # Only try to leave if meeting hasn't already ended
        if not meeting_ended:
            print("Leaving meeting...")
            try:
                leave_button = page.locator('button[aria-label*="Leave call"]')
                if leave_button.count() > 0:
                    leave_button.click()
                    time.sleep(2)
            except:
                pass
        
        browser.close()
        
        print("\n" + "="*70)
        print("Bot stopped")
        print(f"Transcripts saved in: {OUTPUT_FOLDER}/")
        print("="*70 + "\n")


def main():
    print("\n" + "="*70)
    print("Google Meet Bot")
    print("="*70 + "\n")
    
    if len(sys.argv) > 1:
        meeting_link = sys.argv[1]
    else:
        meeting_link = input("Enter Google Meet link: ").strip()
    
    if not meeting_link:
        print("Error: Meeting link is required")
        sys.exit(1)
    
    if "meet.google.com" not in meeting_link:
        print("Error: Invalid Google Meet link")
        sys.exit(1)
    
    try:
        join_meeting(meeting_link)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()