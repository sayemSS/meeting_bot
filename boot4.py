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

# Audio recording settings
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
        # Open audio stream
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
        
        # Stop and close stream
        stream.stop_stream()
        stream.close()
        
        # Save audio file
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
    speaker_stats = {}  # Track who spoke how many times
    
    with open(transcript_file, 'w', encoding='utf-8') as f:
        f.write(f"Meeting Transcript - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 70 + "\n\n")
    
    print(f"Transcript: {transcript_file}")
    
    # Try to enable captions for speaker identification
    print("Attempting to enable captions for speaker tracking...")
    try:
        enable_captions(page)
    except Exception as e:
        print(f"Could not enable captions: {e}")
        print("Transcription will continue without speaker names")
    
    while is_recording:
        try:
            # Try to get speaker from captions
            current_speaker = get_current_speaker_from_caption(page)
            
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = recognizer.listen(source, timeout=RECORD_CHUNK_SECONDS, 
                                        phrase_time_limit=RECORD_CHUNK_SECONDS)
                
                try:
                    text = recognizer.recognize_google(audio, language='en-US')
                    
                    if text.strip():
                        time_str = datetime.now().strftime('%H:%M:%S')
                        
                        # Format with speaker name if available
                        if current_speaker and current_speaker != "Unknown":
                            output = f"[{time_str}] {current_speaker}: {text}\n"
                            
                            # Update speaker stats
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
    
    # Save speaker statistics to metadata
    if speaker_stats:
        meeting_metadata["speaker_stats"] = speaker_stats
        print(f"\n📊 Speaker Statistics:")
        for speaker, count in sorted(speaker_stats.items(), key=lambda x: x[1], reverse=True):
            print(f"  {speaker}: {count} utterances")




def enable_captions(page):
    """Try to enable captions in Google Meet for speaker identification"""
    try:
        # Click on more options (three dots)
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
        
        # Click on captions option
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
        
        # Press Escape to close menu
        page.keyboard.press('Escape')
        return False
    
    except Exception as e:
        print(f"  Could not enable captions: {e}")
        return False


def get_current_speaker_from_caption(page):
    """Extract current speaker name from Google Meet captions"""
    try:
        # Google Meet caption selectors
        caption_selectors = [
            '[jsname="YSxPC"]',  # Google Meet caption container
            '[class*="caption"]',
            '[aria-live="polite"]',
            '[class*="Subtitles"]'
        ]
        
        for selector in caption_selectors:
            try:
                captions = page.locator(selector)
                if captions.count() > 0:
                    # Get the most recent caption
                    caption_text = captions.first.inner_text().strip()
                    
                    if caption_text and ':' in caption_text:
                        # Format is usually "Speaker Name: text"
                        speaker_name = caption_text.split(':')[0].strip()
                        
                        # Validate speaker name
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
        # URL format: https://meet.google.com/abc-defg-hij
        parts = url.split('meet.google.com/')
        if len(parts) > 1:
            return parts[1].split('?')[0]
    except:
        pass
    return "unknown"


def extract_participants(page):
    """Extract participant names from meeting using hybrid approach"""
    participants = []
    participant_count = 0
    
    print("Extracting participants (Method 1: Participant Panel)...")
    
    try:
        # METHOD 1: Try to open participant panel and extract names
        participant_button_selectors = [
            'button[aria-label*="Show everyone" i]',
            'button[aria-label*="People" i]',
            'div[aria-label*="Show everyone" i]',
            'button[jsname="A5il2e"]',  # Google Meet specific
            '[data-tooltip*="people" i]',
            '[aria-label*="participants" i]',
            'button[data-is-muted]',  # Alternative selector
            'div[role="button"][aria-label*="participant" i]'
        ]
        
        panel_opened = False
        
        # Try multiple times with delays
        for attempt in range(3):
            print(f"  Attempt {attempt + 1}/3 to find participant panel...")
            
            for selector in participant_button_selectors:
                try:
                    buttons = page.locator(selector)
                    if buttons.count() > 0:
                        # Try to get participant count from aria-label
                        aria_label = buttons.first.get_attribute('aria-label') or ''
                        print(f"  Found button: {aria_label}")
                        
                        # Extract count from aria-label (e.g., "Show everyone (5)")
                        count_match = re.search(r'\((\d+)\)', aria_label)
                        if count_match:
                            participant_count = int(count_match.group(1))
                            print(f"  Participant count: {participant_count}")
                        
                        # Click to open panel
                        buttons.first.click()
                        print("  ✓ Clicked participant panel button")
                        panel_opened = True
                        time.sleep(3)  # Increased wait time for panel to open
                        break
                except Exception as e:
                    continue
            
            if panel_opened:
                break
            
            # Wait before retry
            time.sleep(2)
        
        # If panel opened, extract names
        if panel_opened:
            print("  Panel opened, extracting names...")
            
            name_selectors = [
                '[data-participant-id] [data-self-name]',
                '[data-participant-id] span',
                '.participant-name',
                '[role="listitem"] span',
                'div[jsname] span[jsname]',
                '[data-requested-participant-id] span',
                '[data-participant-id]',  # Try parent element
                'div[data-self-name]',
                'span[data-self-name]'
            ]
            
            time.sleep(3)  # Extra wait for names to load
            
            # Common UI text to skip
            skip_words = [
                'you', 'mute', 'unmute', 'more', 'pin', 'menu', 
                'options', 'present', 'raise', 'hand', 'settings',
                'turn', 'off', 'on', 'camera', 'microphone',
                'visual_effects', 'backgrounds', 'effects',
                'blur', 'background', 'virtual', 'filters'
            ]
            
            for selector in name_selectors:
                try:
                    name_elements = page.locator(selector)
                    count = name_elements.count()
                    
                    if count > 0:
                        print(f"  Found {count} elements with selector: {selector[:50]}")
                        
                        for i in range(min(count, 50)):  # Max 50 participants
                            try:
                                element = name_elements.nth(i)
                                
                                # Try multiple attributes
                                name = None
                                
                                # Try data-self-name attribute
                                name = element.get_attribute('data-self-name')
                                if not name:
                                    # Try inner text
                                    name = element.inner_text().strip()
                                
                                # Clean the name
                                if name:
                                    # Remove newlines and extra whitespace
                                    name = ' '.join(name.split())
                                    
                                    # Split by newline and take first part
                                    if '\n' in name:
                                        name = name.split('\n')[0].strip()
                                    
                                    # Validate and filter
                                    if len(name) > 1 and name not in participants:
                                        # Convert to lowercase for checking
                                        name_lower = name.lower()
                                        
                                        # Skip if contains UI keywords
                                        if any(skip in name_lower for skip in skip_words):
                                            continue
                                        
                                        # Skip if only digits
                                        if name.isdigit():
                                            continue
                                        
                                        # Skip if too long (likely UI text)
                                        if len(name) > 50:
                                            continue
                                        
                                        # Skip if contains special UI characters
                                        if any(char in name for char in ['→', '•', '▼', '▲']):
                                            continue
                                        
                                        participants.append(name)
                                        print(f"    ✓ Added: {name}")
                            except:
                                continue
                        
                        if participants:
                            break
                except Exception as e:
                    continue
            
            # Close panel
            try:
                page.keyboard.press('Escape')
                time.sleep(1)
            except:
                pass
    
    except Exception as e:
        print(f"  Method 1 failed: {e}")
    
    # METHOD 2: Try to extract from captions if Method 1 failed
    if not participants:
        print("\nExtracting participants (Method 2: Captions)...")
        try:
            # Look for caption elements that show speaker names
            caption_selectors = [
                '[class*="caption"] span',
                '[aria-live="polite"] span',
                '[data-sender-name]'
            ]
            
            for selector in caption_selectors:
                try:
                    elements = page.locator(selector)
                    for i in range(min(elements.count(), 10)):
                        text = elements.nth(i).inner_text().strip()
                        # Caption format is usually "Name: text"
                        if ':' in text:
                            name = text.split(':')[0].strip()
                            if name and name not in participants and len(name) > 1:
                                participants.append(name)
                                print(f"  ✓ From caption: {name}")
                except:
                    continue
            
            if participants:
                print(f"  Found {len(participants)} participants from captions")
        
        except Exception as e:
            print(f"  Method 2 failed: {e}")
    
    # Remove duplicates while preserving order
    seen = set()
    unique_participants = []
    for p in participants:
        if p not in seen:
            seen.add(p)
            unique_participants.append(p)
    
    participants = unique_participants
    
    # METHOD 3: Fallback - at least show participant count
    if not participants and participant_count > 0:
        print(f"\nFallback: Creating participant list based on count ({participant_count})")
        for i in range(participant_count):
            participants.append(f"Participant {i+1}")
    
    # Final fallback
    if not participants:
        participants = ["Unknown (Could not extract names)"]
        print("\n  ⚠ Could not extract participant names")
        print("  💡 Tip: Try manually opening the participant panel or enabling captions")
    else:
        print(f"\n  ✓ Successfully extracted {len(participants)} unique participants")
    
    return participants


def extract_meeting_title(page):
    """Extract meeting title from page"""
    try:
        # Try to get meeting title from page title or meeting info
        title = page.title()
        
        # Clean up title
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
    print("Google Meet Bot - Enhanced Version")
    print("="*70)
    print(f"Meeting: {meeting_url}")
    print(f"Bot Name: {BOT_NAME}")
    print("Features: Audio Recording + Transcription + Metadata")
    print("Press Ctrl+C to stop")
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
        "speaker_stats": {},  # Track who spoke how many times
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
                'div[aria-label*="Turn off camera" i]'
            ]
            
            camera_turned_off = False
            for selector in camera_selectors:
                try:
                    buttons = page.locator(selector)
                    for i in range(buttons.count()):
                        button = buttons.nth(i)
                        aria_label = button.get_attribute('aria-label') or ''
                        
                        if 'turn off' in aria_label.lower() and 'camera' in aria_label.lower():
                            button.click()
                            print("Camera turned OFF")
                            camera_turned_off = True
                            break
                    
                    if camera_turned_off:
                        break
                except:
                    continue
            
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
        
        # Extract meeting metadata
        print("Extracting meeting metadata...")
        meeting_metadata["title"] = extract_meeting_title(page)
        meeting_metadata["status"] = "active"
        
        print("Waiting for page to fully load...")
        time.sleep(5)  # Increased wait time for better stability
        
        # Extract participants (after joining and waiting)
        print("\nExtracting participants...")
        meeting_metadata["participants"] = extract_participants(page)
        meeting_metadata["participant_count"] = len(meeting_metadata["participants"])
        
        print(f"\nMeeting Title: {meeting_metadata['title']}")
        print(f"Participants ({meeting_metadata['participant_count']}): {', '.join(meeting_metadata['participants'][:5])}", end="")
        if meeting_metadata['participant_count'] > 5:
            print(f" ... and {meeting_metadata['participant_count'] - 5} more")
        else:
            print()
        print()
        
        # Save initial metadata
        save_metadata(metadata_file, meeting_metadata)
        
        # Start audio recording
        print("Starting audio recording...")
        is_recording = True
        recording_thread = threading.Thread(target=record_audio, args=(audio_file,), daemon=True)
        recording_thread.start()
        
        time.sleep(1)
        
        # Start transcription
        print("Starting transcription with speaker tracking...")
        print("-"*70 + "\n")
        
        audio_thread = threading.Thread(target=transcribe_audio, args=(transcript_file, page), daemon=True)
        audio_thread.start()
        
        # Monitor meeting
        print("Bot is active. Monitoring meeting status...\n")
        
        try:
            meeting_ended = False
            check_interval = 5
            
            while True:
                try:
                    leave_button = page.locator('button[aria-label*="Leave call"]')
                    
                    if leave_button.count() == 0:
                        meeting_ended = True
                        print("\n" + "="*70)
                        print("Meeting has ended (host closed the meeting)")
                        print("="*70)
                        break
                    
                    current_url = page.url
                    if "meet.google.com" not in current_url:
                        meeting_ended = True
                        print("\n" + "="*70)
                        print("Left the meeting (redirected)")
                        print("="*70)
                        break
                    
                    left_messages = page.locator('text=/You left|meeting ended|has ended/i')
                    if left_messages.count() > 0:
                        meeting_ended = True
                        print("\n" + "="*70)
                        print("Meeting ended or you were removed")
                        print("="*70)
                        break
                
                except Exception as e:
                    print(f"\nError checking meeting status: {e}")
                    meeting_ended = True
                    break
                
                time.sleep(check_interval)
        
        except KeyboardInterrupt:
            print("\n\nStopping bot (Ctrl+C pressed)...")
        
        # Stop recording
        is_recording = False
        
        print("\nStopping recordings...")
        
        if audio_thread:
            audio_thread.join(timeout=5)
        
        if recording_thread:
            recording_thread.join(timeout=5)
        
        # Update metadata with end time
        end_time = datetime.now()
        meeting_metadata["end_time"] = end_time.strftime('%Y-%m-%d %H:%M:%S')
        meeting_metadata["status"] = "completed"
        
        # Calculate duration
        start_dt = datetime.strptime(meeting_metadata["start_time"], '%Y-%m-%d %H:%M:%S')
        duration = (end_time - start_dt).total_seconds() / 60
        meeting_metadata["duration_minutes"] = round(duration, 2)
        
        # Save final metadata
        save_metadata(metadata_file, meeting_metadata)
        
        # Leave meeting if not already left
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
        print("Bot stopped successfully")
        print("="*70)
        print(f"\n📁 Meeting folder: {meeting_folder}")
        print(f"\n📄 Files created:")
        print(f"  🎵 Audio: {os.path.basename(audio_file)}")
        print(f"     Path: {audio_file}")
        print(f"  📝 Transcript: {os.path.basename(transcript_file)}")
        print(f"     Path: {transcript_file}")
        print(f"  📊 Metadata: {os.path.basename(metadata_file)}")
        print(f"     Path: {metadata_file}")
        print(f"\n⏱️  Duration: {meeting_metadata['duration_minutes']} minutes")
        print(f"👥 Participants: {meeting_metadata['participant_count']}")
        print("="*70 + "\n")


def main():
    print("\n" + "="*70)
    print("Google Meet Bot - Enhanced Version")
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