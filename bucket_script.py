import boto3
import json
import time
import uuid
from datetime import datetime
from typing import Optional, List, Dict
from dataclasses import dataclass
from urllib.parse import urlparse
import logging
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class TranscribeJobDto:
    """Transcription job information"""
    job_name: str
    status: str
    creation_time: Optional[datetime] = None
    completion_time: Optional[datetime] = None


class TranscribeService:
    """AWS Transcribe service for audio transcription with speaker diarization"""
    
    def __init__(
        self,
        audio_bucket: str,
        output_bucket: str,
        language_code: str = "bn-IN",
        max_speakers: int = 10,
        output_prefix: str = "transcribe-raw/",
        region_name: str = "us-east-1"
    ):
        self.audio_bucket = audio_bucket
        self.output_bucket = output_bucket
        self.language_code = language_code
        self.max_speakers = max_speakers
        self.output_prefix = output_prefix
        
        # Initialize AWS clients
        self.transcribe_client = boto3.client('transcribe', region_name=region_name)
        self.s3_client = boto3.client('s3', region_name=region_name)
    
    def start_job_for_s3_audio(
        self,
        audio_bucket: str,
        audio_key: str,
        media_format: str
    ) -> str:
        """Start transcription job with speaker diarization"""
        self._validate_input(audio_bucket, audio_key, media_format)
        
        job_name = self._generate_job_name()
        media_uri = self._build_s3_uri(audio_bucket, audio_key)
        output_key = f"{self.output_prefix}{job_name}.json"
        
        logger.info(f"Starting Transcribe Job | job={job_name} | input={media_uri}")
        
        try:
            response = self.transcribe_client.start_transcription_job(
                TranscriptionJobName=job_name,
                Media={'MediaFileUri': media_uri},
                MediaFormat=media_format,
                LanguageCode=self.language_code,
                OutputBucketName=self.output_bucket,
                OutputKey=output_key,
                Settings={
                    'ShowSpeakerLabels': True,
                    'MaxSpeakerLabels': self.max_speakers
                }
            )
            
            return response['TranscriptionJob']['TranscriptionJobName']
        
        except Exception as e:
            logger.error(f"Failed to start transcription job: {e}")
            raise
    
    def get_job_status(self, job_name: str) -> str:
        """Get transcription job status"""
        job = self._get_job(job_name)
        return job['TranscriptionJobStatus']
    
    def get_transcript_text(self, job_name: str) -> str:
        """Get final transcript text with speaker labels"""
        job = self._get_job(job_name)
        
        status = job['TranscriptionJobStatus']
        
        if status == 'FAILED':
            failure_reason = job.get('FailureReason', 'Unknown')
            logger.error(f"Transcription failed | job={job_name} | reason={failure_reason}")
            raise Exception(f"Transcription failed: {failure_reason}")
        
        if status != 'COMPLETED':
            raise Exception(f"Transcription not completed yet. Status: {status}")
        
        transcript_uri = job['Transcript']['TranscriptFileUri']
        bucket, key = self._parse_s3_location(transcript_uri)
        
        return self._read_transcript_from_s3(bucket, key)
    
    def wait_for_completion(
        self,
        job_name: str,
        check_interval: int = 10,
        max_wait_time: int = 3600
    ) -> str:
        """Wait for transcription job to complete"""
        start_time = time.time()
        
        while True:
            status = self.get_job_status(job_name)
            
            if status in ['COMPLETED', 'FAILED']:
                return status
            
            elapsed = time.time() - start_time
            if elapsed > max_wait_time:
                raise TimeoutError(f"Job did not complete within {max_wait_time} seconds")
            
            logger.info(f"Job {job_name} status: {status}. Waiting...")
            time.sleep(check_interval)
    
    def list_all_jobs(self, status: Optional[str] = None) -> List[TranscribeJobDto]:
        """List all transcription jobs with pagination"""
        all_jobs = []
        next_token = None
        
        while True:
            params = {'MaxResults': 100}
            
            if status:
                params['Status'] = status
            if next_token:
                params['NextToken'] = next_token
            
            response = self.transcribe_client.list_transcription_jobs(**params)
            
            for job_summary in response.get('TranscriptionJobSummaries', []):
                all_jobs.append(TranscribeJobDto(
                    job_name=job_summary['TranscriptionJobName'],
                    status=job_summary['TranscriptionJobStatus'],
                    creation_time=job_summary.get('CreationTime'),
                    completion_time=job_summary.get('CompletionTime')
                ))
            
            next_token = response.get('NextToken')
            if not next_token:
                break
        
        return all_jobs
    
    def cleanup_job_and_files(self, audio_key: str, job_name: str):
        """Delete audio file, transcript file, and transcription job"""
        # Delete original audio from S3
        try:
            self.s3_client.delete_object(Bucket=self.audio_bucket, Key=audio_key)
            logger.info(f"Deleted audio file | bucket={self.audio_bucket} | key={audio_key}")
        except Exception as e:
            logger.warning(f"Failed to delete audio file | error={e}")
        
        # Delete transcript JSON from S3
        transcript_key = f"{self.output_prefix}{job_name}.json"
        try:
            self.s3_client.delete_object(Bucket=self.output_bucket, Key=transcript_key)
            logger.info(f"Deleted transcript file | bucket={self.output_bucket} | key={transcript_key}")
        except Exception as e:
            logger.warning(f"Failed to delete transcript file | error={e}")
        
        # Delete Transcribe job
        try:
            self.transcribe_client.delete_transcription_job(TranscriptionJobName=job_name)
            logger.info(f"Deleted Transcribe job | jobName={job_name}")
        except Exception as e:
            logger.warning(f"Failed to delete Transcribe job | error={e}")
    
    # Private helper methods
    
    def _get_job(self, job_name: str) -> Dict:
        """Get transcription job details"""
        response = self.transcribe_client.get_transcription_job(
            TranscriptionJobName=job_name
        )
        return response['TranscriptionJob']
    
    def _read_transcript_from_s3(self, bucket: str, key: str) -> str:
        """Read and parse transcript JSON from S3"""
        try:
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            content = response['Body'].read().decode('utf-8')
            data = json.loads(content)
            
            results = data.get('results', {})
            
            # Try to build diarized transcript
            diarized = self._build_diarized_transcript(results)
            if diarized:
                return diarized
            
            # Fallback to simple transcript
            transcripts = results.get('transcripts', [])
            if transcripts:
                return transcripts[0].get('transcript', '')
            
            return ''
        
        except Exception as e:
            logger.error(f"Failed to read transcript from S3: {e}")
            raise
    
    def _build_diarized_transcript(self, results: Dict) -> Optional[str]:
        """Build speaker-labeled transcript"""
        speaker_labels = results.get('speaker_labels', {})
        segments = speaker_labels.get('segments', [])
        items = results.get('items', [])
        
        if not segments or not items:
            return None
        
        # Map start_time -> index in items array
        index_by_start = {}
        for i, item in enumerate(items):
            start_time = item.get('start_time')
            if start_time:
                index_by_start[start_time] = i
        
        # Map AWS speaker labels to friendly names
        speaker_name_map = {}
        transcript_lines = []
        
        for segment in segments:
            aws_label = segment.get('speaker_label', 'unknown')
            
            if aws_label not in speaker_name_map:
                speaker_name_map[aws_label] = f"Speaker {len(speaker_name_map) + 1}"
            
            display_name = speaker_name_map[aws_label]
            
            seg_items = segment.get('items', [])
            if not seg_items:
                continue
            
            words = []
            
            for seg_item in seg_items:
                start_time = seg_item.get('start_time')
                if not start_time:
                    continue
                
                idx = index_by_start.get(start_time)
                if idx is None or idx >= len(items):
                    continue
                
                word_item = items[idx]
                alternatives = word_item.get('alternatives', [])
                if not alternatives:
                    continue
                
                word = alternatives[0].get('content', '')
                if word:
                    words.append(word)
                    
                    # Check for punctuation
                    if idx + 1 < len(items):
                        next_item = items[idx + 1]
                        if next_item.get('type') == 'punctuation':
                            punct_alt = next_item.get('alternatives', [])
                            if punct_alt:
                                punct = punct_alt[0].get('content', '')
                                if punct:
                                    words[-1] += punct
            
            if words:
                line = f"{display_name}: {' '.join(words)}"
                transcript_lines.append(line)
        
        return '\n'.join(transcript_lines) if transcript_lines else None
    
    def _validate_input(self, bucket: str, key: str, media_format: str):
        """Validate input parameters"""
        if not bucket or not key or not media_format:
            raise ValueError("bucket, key and media_format must not be empty")
    
    def _generate_job_name(self) -> str:
        """Generate unique job name"""
        timestamp = int(datetime.now().timestamp() * 1000)
        unique_id = str(uuid.uuid4())
        return f"tx-{timestamp}-{unique_id}"
    
    def _build_s3_uri(self, bucket: str, key: str) -> str:
        """Build S3 URI"""
        return f"s3://{bucket}/{key}"
    
    def _parse_s3_location(self, uri_string: str) -> tuple:
        """Parse S3 URI to extract bucket and key"""
        try:
            parsed = urlparse(uri_string)
            
            if parsed.scheme == 's3':
                bucket = parsed.netloc
                key = parsed.path.lstrip('/')
                return bucket, key
            
            # Handle https:// S3 URLs
            if 's3.amazonaws.com' in parsed.netloc:
                path_parts = parsed.path.lstrip('/').split('/', 1)
                bucket = path_parts[0]
                key = path_parts[1] if len(path_parts) > 1 else ''
                return bucket, key
            
            if '.s3.' in parsed.netloc:
                bucket = parsed.netloc.split('.s3.')[0]
                key = parsed.path.lstrip('/')
                return bucket, key
            
            raise ValueError(f"Unsupported S3 URI: {uri_string}")
        
        except Exception as e:
            raise ValueError(f"Failed to parse S3 URI: {uri_string}") from e

# bucket_script.py - main section replace koro

if __name__ == "__main__":
    # Get configuration from environment variables
    audio_bucket = os.getenv("AUDIO_BUCKET", "my-audio-bucket")
    output_bucket = os.getenv("OUTPUT_BUCKET", "my-output-bucket")
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    
    # Initialize service FIRST
    service = TranscribeService(
        audio_bucket=audio_bucket,
        output_bucket=output_bucket,
        language_code="bn-IN",
        max_speakers=10,
        region_name=region
    )
    
    # List available buckets
    print("Checking available S3 buckets...")
    try:
        response = service.s3_client.list_buckets()
        print("Available buckets:")
        for bucket in response['Buckets']:
            print(f"  - {bucket['Name']}")
    except Exception as e:
        print(f"Error listing buckets: {e}")
    
    # Check if audio file exists
    print(f"\nChecking if file exists in bucket: {audio_bucket}")
    try:
        service.s3_client.head_object(Bucket=audio_bucket, Key="audio/meeting.mp3")
        print("✓ Audio file exists")
    except Exception as e:
        print(f"✗ Audio file not found: {e}")
    
    # List files in audio bucket
    print(f"\nListing files in {audio_bucket}:")
    try:
        response = service.s3_client.list_objects_v2(Bucket=audio_bucket, MaxKeys=10)
        if 'Contents' in response:
            for obj in response['Contents']:
                print(f"  - {obj['Key']}")
        else:
            print("  (no files found)")
    except Exception as e:
        print(f"  Error: {e}")
    
    # Check output bucket write permission
    print(f"\nTesting write permission on {output_bucket}:")
    try:
        test_key = "test-transcribe-access.txt"
        service.s3_client.put_object(
            Bucket=output_bucket,
            Key=test_key,
            Body=b"test"
        )
        print("✓ Can write to output bucket")
        
        # Clean up
        service.s3_client.delete_object(Bucket=output_bucket, Key=test_key)
        print("✓ Can delete from output bucket")
    except Exception as e:
        print(f"✗ Cannot write to output bucket: {e}")
    
    print("\n" + "="*50)
    print("Do you want to start transcription? (yes/no)")
    choice = input().strip().lower()
    
    if choice == 'yes':
        # Start transcription job
        job_name = service.start_job_for_s3_audio(
            audio_bucket=audio_bucket,
            audio_key="audio/meeting.mp3",
            media_format="mp3"
        )
        
        print(f"Started job: {job_name}")
        
        # Wait for completion
        status = service.wait_for_completion(job_name)
        print(f"Job completed with status: {status}")
        
        # Get transcript
        if status == "COMPLETED":
            transcript = service.get_transcript_text(job_name)
            print("\nTranscript:")
            print(transcript)
            
            # Optional: Cleanup
            # service.cleanup_job_and_files("audio/meeting.mp3", job_name)
    else:
        print("Skipping transcription.")