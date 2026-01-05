from playwright.sync_api import sync_playwright
import time
import threading
import speech_recognition as sr
from datetime import datetime
import os
import sys
import json
import pyaudio
import wave
import re


BOT_NAME = "Test Bot"
OUTPUT_FOLDER = "transcripts"
RECORD_CHUNK_SECONDS = 5


AUDIO_FORMAT = pyaudio.paInt16
AUDIO_CHANNELS = 2
AUDIO_RATE = 44100
AUDIO_CHUNK = 1024

if not os.path.exists(OUTPUT_FOLDER):
    os.makedirs(OUTPUT_FOLDER)

is_recording = False
audio_thread = None
recording_thread = None
meeting_metadata = {}


def record_audio(audio_file_path):
    """Record system audio to WAV file"""
    global is_recording
    
    print("Starting audio recording...")
    
    audio = pyaudio.PyAudio()
    
    try:
        stream = audio.open(
            format=AUDIO_FORMAT,
            channels=AUDIO_CHANNELS,
            rate=AUDIO_RATE,
            input=True,
            frames_per_buffer=AUDIO_CHUNK
        )
        
        frames = []
        
        print(f"Recording audio to: {audio_file_path}")
        
        while is_recording:
            try:
                data = stream.read(AUDIO_CHUNK, exception_on_overflow=False)
                frames.append(data)
            except Exception as e:
                print(f"Audio recording error: {e}")
                continue
        
        stream.stop_stream()
        stream.close()
        
        with wave.open(audio_file_path, 'wb') as wf:
            wf.setnchannels(AUDIO_CHANNELS)
            wf.setsampwidth(audio.get_sample_size(AUDIO_FORMAT))
            wf.setframerate(AUDIO_RATE)
            wf.writeframes(b''.join(frames))
        
        print(f"Audio saved: {audio_file_path}")
    
    except Exception as e:
        print(f"Audio recording failed: {e}")
    
    finally:
        audio.terminate()


def transcribe_audio(transcript_file, page):
    """Transcribe meeting audio in real-time with speaker identification"""
    global is_recording, meeting_metadata
    
    recognizer = sr.Recognizer()
    speaker_stats = {}  
    
    with open(transcript_file, 'w', encoding='utf-8') as f:
        f.write(f"Meeting Transcript - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 70 + "\n\n")
    
    print(f"Transcript: {transcript_file}")
    
    print("Attempting to enable captions for speaker tracking...")
    try:
        enable_captions(page)
    except Exception as e:
        print(f"Could not enable captions: {e}")
        print("Transcription will continue without speaker names")
    
    while is_recording:
        try:
            current_speaker = get_current_speaker_from_caption(page)
            
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = recognizer.listen(source, timeout=RECORD_CHUNK_SECONDS, 
                                        phrase_time_limit=RECORD_CHUNK_SECONDS)
                
                try:
                    text = recognizer.recognize_google(audio, language='en-US')
                    
                    if text.strip():
                        time_str = datetime.now().strftime('%H:%M:%S')
                        
                        if current_speaker and current_speaker != "Unknown":
                            output = f"[{time_str}] {current_speaker}: {text}\n"
                            
                            if current_speaker not in speaker_stats:
                                speaker_stats[current_speaker] = 0
                            speaker_stats[current_speaker] += 1
                        else:
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
    
    if speaker_stats:
        meeting_metadata["speaker_stats"] = speaker_stats
        print(f"\n📊 Speaker Statistics:")
        for speaker, count in sorted(speaker_stats.items(), key=lambda x: x[1], reverse=True):
            print(f"  {speaker}: {count} utterances")


def enable_captions(page):
    """Try to enable captions in Google Meet for speaker identification"""
    try:
        more_button_selectors = [
            'button[aria-label*="More options" i]',
            'button[aria-label*="More" i]',
            '[data-tooltip*="More" i]'
        ]
        
        for selector in more_button_selectors:
            try:
                buttons = page.locator(selector)
                if buttons.count() > 0:
                    buttons.first.click()
                    time.sleep(1)
                    break
            except:
                continue
        
        caption_selectors = [
            'text="Turn on captions"',
            'text="Captions"',
            '[aria-label*="caption" i]',
            'span:has-text("captions")'
        ]
        
        for selector in caption_selectors:
            try:
                elements = page.locator(selector)
                if elements.count() > 0:
                    elements.first.click()
                    print("  ✓ Captions enabled for speaker tracking")
                    time.sleep(1)
                    return True
            except:
                continue
        
        page.keyboard.press('Escape')
        return False
    
    except Exception as e:
        print(f"  Could not enable captions: {e}")
        return False


def get_current_speaker_from_caption(page):
    """Extract current speaker name from Google Meet captions"""
    try:
        caption_selectors = [
            '[jsname="YSxPC"]',
            '[class*="caption"]',
            '[aria-live="polite"]',
            '[class*="Subtitles"]'
        ]
        
        for selector in caption_selectors:
            try:
                captions = page.locator(selector)
                if captions.count() > 0:
                    caption_text = captions.first.inner_text().strip()
                    
                    if caption_text and ':' in caption_text:
                        speaker_name = caption_text.split(':')[0].strip()
                        
                        if speaker_name and len(speaker_name) > 1 and not speaker_name.isdigit():
                            return speaker_name
            except:
                continue
        
        return "Unknown"
    
    except Exception as e:
        return "Unknown"


def extract_meeting_code(url):
    """Extract meeting code from URL"""
    try:
        parts = url.split('meet.google.com/')
        if len(parts) > 1:
            return parts[1].split('?')[0]
    except:
        pass
    return "unknown"


def diagnose_page_structure(page, meeting_folder):
    """Take screenshots and analyze page structure to help identify correct selectors"""
    
    print("\n" + "="*70)
    print("DIAGNOSTIC MODE - ANALYZING PAGE STRUCTURE")
    print("="*70)
    
    try:
        # Take screenshot of entire page
        screenshot_path = os.path.join(meeting_folder, "screenshot_full.png")
        page.screenshot(path=screenshot_path)
        print(f"\n✓ Screenshot saved: {screenshot_path}")
        
        # Try to find and click participant button
        print("\n[Step 1] Looking for participant button...")
        
        all_buttons = page.locator('button')
        button_count = all_buttons.count()
        print(f"  Found {button_count} total buttons on page")
        
        participant_button_found = False
        
        for i in range(button_count):
            try:
                button = all_buttons.nth(i)
                aria_label = button.get_attribute('aria-label') or ''
                
                # Look for buttons related to participants
                if any(keyword in aria_label.lower() for keyword in ['people', 'participant', 'everyone', 'show']):
                    print(f"\n  Button {i}: {aria_label}")
                    
                    # Try to click it
                    try:
                        button.click()
                        print(f"  ✓ Clicked button")
                        participant_button_found = True
                        time.sleep(3)
                        
                        # Take screenshot after clicking
                        screenshot_panel = os.path.join(meeting_folder, "screenshot_panel_open.png")
                        page.screenshot(path=screenshot_panel)
                        print(f"  ✓ Screenshot saved: {screenshot_panel}")
                        
                        break
                    except Exception as e:
                        print(f"  ✗ Could not click: {e}")
            except:
                continue
        
        if not participant_button_found:
            print("\n  ✗ Could not find participant button")
            print("\n  Trying keyboard shortcut Ctrl+Alt+P...")
            try:
                page.keyboard.press('Control+Alt+P')
                time.sleep(3)
                screenshot_panel = os.path.join(meeting_folder, "screenshot_panel_keyboard.png")
                page.screenshot(path=screenshot_panel)
                print(f"  ✓ Screenshot saved: {screenshot_panel}")
            except:
                print("  ✗ Keyboard shortcut failed")
        
        # Analyze DOM structure
        print("\n[Step 2] Analyzing DOM for participant data...")
        
        # Save page HTML
        html_path = os.path.join(meeting_folder, "page_structure.html")
        html_content = page.content()
        
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"  ✓ HTML saved: {html_path}")
        
        # Look for data-self-name attributes
        print("\n[Step 3] Searching for data-self-name attributes...")
        self_name_pattern = r'data-self-name="([^"]+)"'
        matches = re.findall(self_name_pattern, html_content)
        
        if matches:
            print(f"  ✓ Found {len(matches)} data-self-name attributes:")
            for i, match in enumerate(matches, 1):
                print(f"    {i}. {match}")
        else:
            print("  ✗ No data-self-name attributes found")
        
        # Look for participant-related attributes
        print("\n[Step 4] Searching for participant-related attributes...")
        participant_patterns = [
            r'data-participant-id="([^"]+)"',
            r'data-requested-participant-id="([^"]+)"',
            r'aria-label="([^"]*participant[^"]*)"i',
        ]
        
        for pattern in participant_patterns:
            matches = re.findall(pattern, html_content, re.IGNORECASE)
            if matches:
                print(f"  Pattern '{pattern}': found {len(matches)} matches")
                for i, match in enumerate(matches[:5], 1):  # Show first 5
                    print(f"    {i}. {match}")
        
        # Look for all elements with role="listitem"
        print("\n[Step 5] Checking list items...")
        list_items = page.locator('[role="listitem"]')
        count = list_items.count()
        print(f"  Found {count} list items")
        
        if count > 0:
            for i in range(min(count, 10)):
                try:
                    item = list_items.nth(i)
                    text = item.inner_text().strip()
                    if text:
                        print(f"    [{i}] {text[:100]}")  # First 100 chars
                except:
                    continue
        
        # Close panel if opened
        try:
            page.keyboard.press('Escape')
            time.sleep(1)
        except:
            pass
        
        print("\n" + "="*70)
        print("DIAGNOSTIC COMPLETE")
        print("="*70)
        print("\nPlease check the following files in your meeting folder:")
        print(f"  1. screenshot_full.png - Full page screenshot")
        print(f"  2. screenshot_panel_open.png - Panel open (if found)")
        print(f"  3. page_structure.html - Complete HTML structure")
        print("\nShare these files to help debug the issue!")
        print("="*70 + "\n")
        
    except Exception as e:
        print(f"\n✗ Diagnostic error: {e}")


def extract_participants(page, meeting_folder):
    """Extract participant names - will run diagnostic if fails"""
    participants = []
    
    print("\n[Standard Extraction] Attempting to extract participants...")
    
    try:
        # Try standard method first
        participant_button_selectors = [
            'button[aria-label*="Show everyone" i]',
            'button[aria-label*="People" i]',
            'button[data-mute-status]',
            'button[data-is-muted]',
        ]
        
        panel_opened = False
        
        for selector in participant_button_selectors:
            try:
                buttons = page.locator(selector)
                if buttons.count() > 0:
                    button = buttons.first
                    button.click()
                    print("  ✓ Panel opened")
                    panel_opened = True
                    time.sleep(4)
                    break
            except:
                continue
        
        if panel_opened:
            elements = page.locator('[data-self-name]')
            count = elements.count()
            
            print(f"  Found {count} elements with data-self-name")
            
            seen_names = set()
            
            for i in range(count):
                try:
                    element = elements.nth(i)
                    name = element.get_attribute('data-self-name')
                    
                    if name:
                        name = name.strip()
                        name_lower = name.lower()
                        
                        if name and 2 <= len(name) <= 50:
                            if name_lower not in seen_names:
                                seen_names.add(name_lower)
                                participants.append(name)
                                print(f"    ✓ Added: {name}")
                
                except:
                    continue
            
            # Close panel
            try:
                page.keyboard.press('Escape')
                time.sleep(1)
            except:
                pass
    
    except Exception as e:
        print(f"  ✗ Standard extraction failed: {e}")
    
    # If no participants found, run diagnostic
    if not participants:
        print("\n⚠ Standard extraction failed. Running diagnostic mode...")
        diagnose_page_structure(page, meeting_folder)
        participants = ["Unknown (Could not extract - see diagnostic files)"]
    else:
        print(f"\n✓ Successfully extracted {len(participants)} participants")
    
    return participants


def extract_meeting_title(page):
    """Extract meeting title from page"""
    try:
        title = page.title()
        
        if "Google Meet" in title:
            title = title.replace(" - Google Meet", "").strip()
        
        if title and title != "Google Meet":
            return title
    except:
        pass
    
    return "Untitled Meeting"


def save_metadata(metadata_file, metadata):
    """Save meeting metadata to JSON file"""
    try:
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        print(f"Metadata saved: {metadata_file}")
    except Exception as e:
        print(f"Error saving metadata: {e}")


def join_meeting(meeting_url):
    global is_recording, audio_thread, recording_thread, meeting_metadata
    
    print("\n" + "="*70)
    print("Google Meet Bot - Diagnostic Version")
    print("="*70)
    print(f"Meeting: {meeting_url}")
    print(f"Bot Name: {BOT_NAME}")
    print("="*70 + "\n")
    
    # Create meeting-specific folder
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    meeting_folder = os.path.join(OUTPUT_FOLDER, f"meeting_{timestamp}")
    os.makedirs(meeting_folder, exist_ok=True)
    
    # File paths
    audio_file = os.path.join(meeting_folder, "audio.wav")
    transcript_file = os.path.join(meeting_folder, "transcript.txt")
    metadata_file = os.path.join(meeting_folder, "metadata.json")
    
    # Initialize metadata
    meeting_metadata = {
        "meeting_code": extract_meeting_code(meeting_url),
        "meeting_url": meeting_url,
        "bot_name": BOT_NAME,
        "start_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "end_time": None,
        "duration_minutes": None,
        "title": None,
        "participants": [],
        "participant_count": 0,
        "speaker_stats": {},
        "audio_file": "audio.wav",
        "audio_file_path": os.path.abspath(audio_file),
        "transcript_file": "transcript.txt",
        "transcript_file_path": os.path.abspath(transcript_file),
        "metadata_file_path": os.path.abspath(metadata_file),
        "meeting_folder": os.path.abspath(meeting_folder),
        "status": "starting"
    }
    
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
        
        # Turn OFF camera
        print("Turning off camera...")
        try:
            camera_selectors = [
                'button[aria-label*="Turn off camera" i]',
                'button[aria-label*="camera" i]',
            ]
            
            for selector in camera_selectors:
                try:
                    buttons = page.locator(selector)
                    for i in range(buttons.count()):
                        button = buttons.nth(i)
                        aria_label = button.get_attribute('aria-label') or ''
                        
                        if 'turn off' in aria_label.lower() and 'camera' in aria_label.lower():
                            button.click()
                            print("Camera turned OFF")
                            break
                except:
                    continue
        except Exception as e:
            print(f"Camera control warning: {e}")
        
        time.sleep(2)
        
        # Join meeting
        print("Joining meeting...")
        
        join_selectors = [
            'button:has-text("Join now")',
            'button:has-text("Ask to join")',
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
                if page.locator('button[aria-label*="Leave call"]').count() > 0:
                    joined = True
                    print("Joined successfully!\n")
                    break
            except:
                continue
        
        if not joined:
            print("Could not confirm join, continuing anyway...\n")
        
        # Extract meeting metadata
        meeting_metadata["title"] = extract_meeting_title(page)
        meeting_metadata["status"] = "active"
        
        # Wait for page to load
        print("Waiting for page to load...")
        time.sleep(8)
        
        # Extract participants (will run diagnostic if fails)
        meeting_metadata["participants"] = extract_participants(page, meeting_folder)
        meeting_metadata["participant_count"] = len(meeting_metadata["participants"])
        
        print(f"\nMeeting Title: {meeting_metadata['title']}")
        print(f"Participants: {', '.join(meeting_metadata['participants'])}\n")
        
        # Save metadata
        save_metadata(metadata_file, meeting_metadata)
        
        # Start audio recording
        print("Starting audio recording...")
        is_recording = True
        recording_thread = threading.Thread(target=record_audio, args=(audio_file,), daemon=True)
        recording_thread.start()
        
        time.sleep(1)
        
        # Start transcription
        print("Starting transcription...")
        audio_thread = threading.Thread(target=transcribe_audio, args=(transcript_file, page), daemon=True)
        audio_thread.start()
        
        print("\nBot is active. Press Ctrl+C to stop\n")
        
        try:
            while True:
                try:
                    if page.locator('button[aria-label*="Leave call"]').count() == 0:
                        print("\nMeeting has ended")
                        break
                except:
                    break
                
                time.sleep(5)
        
        except KeyboardInterrupt:
            print("\n\nStopping bot...")
        
        # Stop recording
        is_recording = False
        print("\nStopping recordings...")
        
        if audio_thread:
            audio_thread.join(timeout=5)
        
        if recording_thread:
            recording_thread.join(timeout=5)
        
        # Update metadata
        end_time = datetime.now()
        meeting_metadata["end_time"] = end_time.strftime('%Y-%m-%d %H:%M:%S')
        meeting_metadata["status"] = "completed"
        
        start_dt = datetime.strptime(meeting_metadata["start_time"], '%Y-%m-%d %H:%M:%S')
        duration = (end_time - start_dt).total_seconds() / 60
        meeting_metadata["duration_minutes"] = round(duration, 2)
        
        save_metadata(metadata_file, meeting_metadata)
        
        # Leave meeting
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
        print("="*70)
        print(f"\n📁 Meeting folder: {meeting_folder}")
        print(f"⏱  Duration: {meeting_metadata['duration_minutes']} minutes")
        print("="*70 + "\n")


def main():
    if len(sys.argv) > 1:
        meeting_link = sys.argv[1]
    else:
        meeting_link = input("Enter Google Meet link: ").strip()
    
    if not meeting_link or "meet.google.com" not in meeting_link:
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