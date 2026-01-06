# app.py - Main FastAPI Application
from fastapi import FastAPI, File, UploadFile, HTTPException, Path
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import boto3
import os
import time
import json
import uuid
from typing import Optional
from dotenv import load_dotenv
import uvicorn
from botocore.exceptions import ClientError

load_dotenv()

app = FastAPI(
    title="Meeting Pilot Backend API",
    description="Audio Transcription Service using AWS Transcribe",
    version="1.0.0"
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# AWS Configuration
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
AUDIO_BUCKET = os.getenv("AUDIO_BUCKET", "mp-s3-demo-dev")
OUTPUT_BUCKET = os.getenv("OUTPUT_BUCKET", "mp-s3-demo-dev")

# Initialize AWS clients
s3_client = boto3.client('s3', region_name=AWS_REGION)
transcribe_client = boto3.client('transcribe', region_name=AWS_REGION)


class TranscriptionService:
    """Service for handling audio transcription"""
    
    @staticmethod
    def get_media_format(filename: str) -> str:
        """Determine media format from filename"""
        ext = filename.split('.')[-1].lower()
        format_map = {
            'mp3': 'mp3',
            'wav': 'wav',
            'mp4': 'mp4',
            'flac': 'flac',
            'm4a': 'mp4',
            'ogg': 'ogg',
            'webm': 'webm'
        }
        return format_map.get(ext, 'mp3')
    
    @staticmethod
    def upload_to_s3(file_content: bytes, filename: str, user_id: str) -> str:
        """Upload file to S3 and return the key"""
        try:
            s3_key = f"users/{user_id}/audio/{filename}"
            s3_client.put_object(
                Bucket=AUDIO_BUCKET,
                Key=s3_key,
                Body=file_content
            )
            return s3_key
        except ClientError as e:
            raise HTTPException(status_code=500, detail=f"S3 upload failed: {str(e)}")
    
    @staticmethod
    def start_transcription(s3_key: str, filename: str, language: str = "en-US") -> str:
        """Start AWS Transcribe job"""
        try:
            job_name = f"tx-{int(time.time() * 1000)}-{str(uuid.uuid4())[:8]}"
            media_uri = f"s3://{AUDIO_BUCKET}/{s3_key}"
            media_format = TranscriptionService.get_media_format(filename)
            output_key = f"transcribe-output/{job_name}.json"
            
            transcribe_client.start_transcription_job(
                TranscriptionJobName=job_name,
                Media={'MediaFileUri': media_uri},
                MediaFormat=media_format,
                LanguageCode=language,
                OutputBucketName=OUTPUT_BUCKET,
                OutputKey=output_key,
                Settings={
                    'ShowSpeakerLabels': True,
                    'MaxSpeakerLabels': 10
                }
            )
            
            return job_name
            
        except ClientError as e:
            raise HTTPException(status_code=500, detail=f"Transcription start failed: {str(e)}")
    
    @staticmethod
    def get_job_status(job_name: str) -> dict:
        """Get transcription job status"""
        try:
            response = transcribe_client.get_transcription_job(
                TranscriptionJobName=job_name
            )
            job = response['TranscriptionJob']
            
            return {
                "jobName": job_name,
                "status": job['TranscriptionJobStatus'],
                "creationTime": job.get('CreationTime', '').isoformat() if job.get('CreationTime') else None,
                "completionTime": job.get('CompletionTime', '').isoformat() if job.get('CompletionTime') else None,
                "failureReason": job.get('FailureReason')
            }
            
        except ClientError as e:
            raise HTTPException(status_code=404, detail=f"Job not found: {str(e)}")
    
    @staticmethod
    def get_transcript(job_name: str) -> dict:
        """Get transcript from completed job"""
        try:
            # Check job status first
            status_response = transcribe_client.get_transcription_job(
                TranscriptionJobName=job_name
            )
            
            job = status_response['TranscriptionJob']
            status = job['TranscriptionJobStatus']
            
            if status != 'COMPLETED':
                return {
                    "status": status,
                    "transcript": None,
                    "failureReason": job.get('FailureReason')
                }
            
            # Get transcript from S3
            output_key = f"transcribe-output/{job_name}.json"
            
            try:
                obj = s3_client.get_object(Bucket=OUTPUT_BUCKET, Key=output_key)
                data = json.loads(obj['Body'].read().decode('utf-8'))
                
                results = data.get('results', {})
                
                # Try speaker-labeled transcript first
                transcript = TranscriptionService._build_speaker_transcript(results)
                
                # Fallback to simple transcript
                if not transcript:
                    transcripts = results.get('transcripts', [])
                    if transcripts:
                        transcript = transcripts[0].get('transcript', '')
                
                return {
                    "status": "COMPLETED",
                    "transcript": transcript,
                    "speakerLabels": results.get('speaker_labels') is not None,
                    "fullResults": results
                }
                
            except ClientError:
                raise HTTPException(status_code=404, detail="Transcript file not found in S3")
                
        except ClientError as e:
            raise HTTPException(status_code=404, detail=f"Job not found: {str(e)}")
    
    @staticmethod
    def _build_speaker_transcript(results: dict) -> Optional[str]:
        """Build transcript with speaker labels"""
        try:
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
                
                for seg_item in segment.get('items', []):
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
                    if alternatives:
                        word = alternatives[0].get('content', '')
                        if word:
                            words.append(word)
                            
                            # Add punctuation
                            if idx + 1 < len(items):
                                next_item = items[idx + 1]
                                if next_item and isinstance(next_item, dict):
                                    if next_item.get('type') == 'punctuation':
                                        punct_alt = next_item.get('alternatives', [])
                                        if punct_alt:
                                            words[-1] += punct_alt[0].get('content', '')
                
                if words:
                    lines.append(f"{display_name}: {' '.join(words)}")
            
            return '\n'.join(lines) if lines else None
            
        except Exception:
            return None


# API Endpoints

@app.get("/")
def root():
    """Health check endpoint"""
    return {
        "service": "Meeting Pilot Backend API",
        "status": "running",
        "version": "1.0.0"
    }


@app.post("/api/users/{user_id}/audio-transcribe/upload-and-start")
async def upload_and_start_transcription(
    user_id: str = Path(..., description="User ID"),
    file: UploadFile = File(...),
    language: str = "en-US"
):
    """
    Upload audio file and start transcription
    
    - **user_id**: User identifier
    - **file**: Audio file (mp3, wav, mp4, flac, m4a, ogg, webm)
    - **language**: Language code (en-US, bn-IN, etc.)
    """
    
    # Validate file
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    
    # Read file content
    file_content = await file.read()
    file_size_mb = len(file_content) / (1024 * 1024)
    
    if file_size_mb > 500:  # 500MB limit
        raise HTTPException(status_code=400, detail="File too large (max 500MB)")
    
    # Upload to S3
    s3_key = TranscriptionService.upload_to_s3(file_content, file.filename, user_id)
    
    # Start transcription
    job_name = TranscriptionService.start_transcription(s3_key, file.filename, language)
    
    return {
        "success": True,
        "message": "Transcription job started",
        "data": {
            "jobName": job_name,
            "userId": user_id,
            "fileName": file.filename,
            "fileSize": f"{file_size_mb:.2f} MB",
            "s3Key": s3_key,
            "language": language
        }
    }


@app.get("/api/transcribe/status/{job_name}")
def get_transcription_status(job_name: str = Path(..., description="Transcription job name")):
    """
    Get transcription job status
    
    - **job_name**: Transcription job identifier
    """
    status = TranscriptionService.get_job_status(job_name)
    
    return {
        "success": True,
        "data": status
    }


@app.get("/api/transcribe/result/{job_name}")
def get_transcription_result(job_name: str = Path(..., description="Transcription job name")):
    """
    Get transcription result
    
    - **job_name**: Transcription job identifier
    """
    result = TranscriptionService.get_transcript(job_name)
    
    if result['status'] != 'COMPLETED':
        return {
            "success": False,
            "message": f"Job status: {result['status']}",
            "data": result
        }
    
    return {
        "success": True,
        "message": "Transcription completed",
        "data": result
    }


@app.delete("/api/transcribe/job/{job_name}")
def delete_transcription_job(job_name: str = Path(..., description="Transcription job name")):
    """
    Delete transcription job
    
    - **job_name**: Transcription job identifier
    """
    try:
        transcribe_client.delete_transcription_job(
            TranscriptionJobName=job_name
        )
        
        return {
            "success": True,
            "message": "Transcription job deleted",
            "data": {"jobName": job_name}
        }
        
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"Job not found: {str(e)}")


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(
        "java_clone_sc:app",
        host="0.0.0.0",
        port=port,
        reload=True
    )