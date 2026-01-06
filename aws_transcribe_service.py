import boto3
import os
import time
import json
import uuid
from dotenv import load_dotenv

load_dotenv()

def transcribe_audio():
    # Configuration
    region = os.getenv("AWS_DEFAULT_REGION", "ap-south-1")
    audio_bucket = os.getenv("AUDIO_BUCKET", "mp-s3-demo-dev")
    output_bucket = os.getenv("OUTPUT_BUCKET", "mp-s3-demo-dev")
    
    print("="*70)
    print("AWS TRANSCRIBE - FINAL VERSION")
    print("="*70)
    print(f"Region: {region}")
    print(f"Audio Bucket: {audio_bucket}")
    print(f"Output Bucket: {output_bucket}")
    print("="*70)
    
    # Initialize clients
    s3 = boto3.client('s3', region_name=region)
    transcribe = boto3.client('transcribe', region_name=region)
    
    # Get audio file
    audio_file = input("\nAudio file path: ").strip()
    if not audio_file:
        audio_file = "file_example_WAV_1MG.wav"
    
    if not os.path.exists(audio_file):
        print(f"✗ File not found: {audio_file}")
        return
    
    # File info
    file_name = os.path.basename(audio_file)
    file_size = os.path.getsize(audio_file) / (1024 * 1024)
    
    print(f"\nFile: {file_name}")
    print(f"Size: {file_size:.2f} MB")
    
    # STEP 1: Upload to S3
    print("\n" + "="*70)
    print("STEP 1: Uploading to S3")
    print("="*70)
    
    s3_key = f"audio/{file_name}"
    
    try:
        print(f"Uploading to s3://{audio_bucket}/{s3_key}...")
        s3.upload_file(audio_file, audio_bucket, s3_key)
        print(f"✓ Upload successful!")
    except Exception as e:
        print(f"✗ Upload failed: {e}")
        return
    
    # STEP 2: Start Transcription
    print("\n" + "="*70)
    print("STEP 2: Starting AWS Transcribe Job")
    print("="*70)
    
    # Determine media format
    ext = file_name.split('.')[-1].lower()
    format_map = {
        'mp3': 'mp3', 'wav': 'wav', 'mp4': 'mp4',
        'flac': 'flac', 'm4a': 'mp4', 'ogg': 'ogg'
    }
    media_format = format_map.get(ext, 'mp3')
    
    # Generate job name
    job_name = f"tx-{int(time.time()*1000)}-{str(uuid.uuid4())[:8]}"
    media_uri = f"s3://{audio_bucket}/{s3_key}"
    output_key = f"transcribe-raw/{job_name}.json"
    
    print(f"Job Name: {job_name}")
    print(f"Media Format: {media_format}")
    print(f"Language: bn-IN (Bengali)")
    
    try:
        transcribe.start_transcription_job(
            TranscriptionJobName=job_name,
            Media={'MediaFileUri': media_uri},
            MediaFormat=media_format,
            LanguageCode='bn-IN',
            OutputBucketName=output_bucket,
            OutputKey=output_key,
            Settings={
                'ShowSpeakerLabels': True,
                'MaxSpeakerLabels': 10
            }
        )
        print(f"✓ Job started successfully!")
    except Exception as e:
        print(f"✗ Failed to start job: {e}")
        return
    
    # STEP 3: Wait for Completion
    print("\n" + "="*70)
    print("STEP 3: Waiting for Transcription")
    print("="*70)
    
    start_time = time.time()
    
    while True:
        try:
            response = transcribe.get_transcription_job(
                TranscriptionJobName=job_name
            )
            status = response['TranscriptionJob']['TranscriptionJobStatus']
            elapsed = int(time.time() - start_time)
            
            print(f"[{elapsed}s] Status: {status}", end='\r')
            
            if status == 'COMPLETED':
                print(f"\n✓ Transcription completed in {elapsed}s!")
                break
            elif status == 'FAILED':
                reason = response['TranscriptionJob'].get('FailureReason', 'Unknown')
                print(f"\n✗ Transcription failed: {reason}")
                return
            
            time.sleep(5)
            
        except Exception as e:
            print(f"\n✗ Error checking status: {e}")
            return
    
    # STEP 4: Download Transcript
    print("\n" + "="*70)
    print("STEP 4: Downloading Transcript")
    print("="*70)
    
    try:
        obj = s3.get_object(Bucket=output_bucket, Key=output_key)
        data = json.loads(obj['Body'].read().decode('utf-8'))
        
        results = data.get('results', {})
        
        # Try to build speaker transcript first
        transcript = build_speaker_transcript(results)
        
        # Fallback to simple transcript
        if not transcript:
            print("Note: Speaker labels not available, using simple transcript")
            transcripts = results.get('transcripts', [])
            if transcripts:
                transcript = transcripts[0].get('transcript', '')
        
        if transcript:
            print("\n" + "="*70)
            print("TRANSCRIPT:")
            print("="*70)
            print(transcript)
            print("="*70)
            
            # Save to file
            output_file = f"transcript_{job_name}.txt"
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(transcript)
            
            print(f"\n✓ Saved to: {output_file}")
            
            # Save JSON
            json_file = f"transcript_{job_name}.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            print(f"✓ JSON saved to: {json_file}")
            
        else:
            print("✗ No transcript found")
            print("\nDebug: Response structure:")
            print(json.dumps(results, indent=2, ensure_ascii=False)[:500])
        
    except Exception as e:
        print(f"✗ Error downloading transcript: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print("\n" + "="*70)
    print("✓ SUCCESSFULLY COMPLETED!")
    print("="*70)


def build_speaker_transcript(results):
    """Build transcript with speaker labels"""
    if not results:
        return None
        
    try:
        # Check if speaker_labels exists and is not None
        speaker_labels = results.get('speaker_labels')
        if not speaker_labels:
            return None
            
        segments = speaker_labels.get('segments', [])
        items = results.get('items', [])
        
        if not segments or not items:
            return None
        
        # Map start_time to index
        index_by_start = {}
        for i, item in enumerate(items):
            if item and isinstance(item, dict):
                start_time = item.get('start_time')
                if start_time:
                    index_by_start[start_time] = i
        
        # Build transcript
        speaker_map = {}
        lines = []
        
        for segment in segments:
            if not segment or not isinstance(segment, dict):
                continue
                
            speaker_label = segment.get('speaker_label', 'unknown')
            
            if speaker_label not in speaker_map:
                speaker_map[speaker_label] = f"Speaker {len(speaker_map) + 1}"
            
            display_name = speaker_map[speaker_label]
            
            words = []
            seg_items = segment.get('items', [])
            
            for seg_item in seg_items:
                if not seg_item or not isinstance(seg_item, dict):
                    continue
                    
                start_time = seg_item.get('start_time')
                if not start_time:
                    continue
                
                idx = index_by_start.get(start_time)
                if idx is None or idx >= len(items):
                    continue
                
                word_item = items[idx]
                if not word_item or not isinstance(word_item, dict):
                    continue
                    
                alternatives = word_item.get('alternatives', [])
                if alternatives and len(alternatives) > 0:
                    word = alternatives[0].get('content', '')
                    if word:
                        words.append(word)
                        
                        # Add punctuation
                        if idx + 1 < len(items):
                            next_item = items[idx + 1]
                            if next_item and isinstance(next_item, dict):
                                if next_item.get('type') == 'punctuation':
                                    punct_alt = next_item.get('alternatives', [])
                                    if punct_alt and len(punct_alt) > 0:
                                        words[-1] += punct_alt[0].get('content', '')
            
            if words:
                lines.append(f"{display_name}: {' '.join(words)}")
        
        return '\n'.join(lines) if lines else None
        
    except Exception as e:
        print(f"Warning: Could not build speaker transcript: {e}")
        return None


if __name__ == "__main__":
    transcribe_audio()