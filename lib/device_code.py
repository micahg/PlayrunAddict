#!/usr/bin/env python3
"""
Google OAuth2 Device Code Flow implementation using aiohttp
"""

import asyncio
import json
import logging
import os
import pickle
import time
from typing import Dict, Any, Optional
import aiohttp
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from lib.config import Config

logger = logging.getLogger(__name__)

class DeviceCodeAuth:
    """Google OAuth2 Device Code Flow implementation using aiohttp"""
    
    def __init__(self, credentials_file: str = 'credentials.json', token_cache_file: str = 'token.pickle'):
        self.credentials_file = credentials_file
        self.token_cache_file = token_cache_file
        self.client_config = self._load_client_config()
        
    def _load_cached_credentials(self) -> Optional[Credentials]:
        """Load cached credentials from file if they exist and are valid"""
        if not os.path.exists(self.token_cache_file):
            logger.info("No cached credentials found")
            return None
            
        try:
            with open(self.token_cache_file, 'rb') as token_file:
                credentials = pickle.load(token_file)
                
            # Check if credentials are valid
            if not credentials.valid:
                if credentials.expired and credentials.refresh_token:
                    logger.info("Cached credentials expired, attempting refresh...")
                    try:
                        credentials.refresh(Request())
                        # Save refreshed credentials
                        self._save_credentials(credentials)
                        logger.info("Successfully refreshed cached credentials")
                        return credentials
                    except Exception as e:
                        logger.warning(f"Failed to refresh credentials: {e}")
                        return None
                else:
                    logger.info("Cached credentials are invalid and cannot be refreshed")
                    return None
            else:
                logger.info("Using cached credentials")
                return credentials
                
        except Exception as e:
            logger.warning(f"Error loading cached credentials: {e}")
            return None
    
    def _save_credentials(self, credentials: Credentials):
        """Save credentials to cache file"""
        try:
            with open(self.token_cache_file, 'wb') as token_file:
                pickle.dump(credentials, token_file)
            logger.info(f"Credentials cached to {self.token_cache_file}")
        except Exception as e:
            logger.warning(f"Failed to cache credentials: {e}")
        
    def _load_client_config(self) -> Dict[str, Any]:
        """Load client configuration from credentials.json"""
        try:
            with open(self.credentials_file, 'r') as f:
                config = json.load(f)
                
            # Handle both formats of credentials.json
            if 'installed' in config:
                return config['installed']
            elif 'web' in config:
                return config['web']
            else:
                raise ValueError("Invalid credentials.json format")
                
        except FileNotFoundError:
            raise FileNotFoundError(f"Credentials file '{self.credentials_file}' not found")
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON in '{self.credentials_file}'")
    
    async def authenticate(self, scopes: list[str]) -> Credentials:
        """
        Perform device code authentication flow with caching
        
        Args:
            scopes: List of OAuth2 scopes to request
            
        Returns:
            Google OAuth2 Credentials object
        """
        # Try to load cached credentials first
        cached_credentials = self._load_cached_credentials()
        if cached_credentials and cached_credentials.valid:
            # Verify scopes match (in case they changed)
            cached_scopes = set(cached_credentials.scopes or [])
            requested_scopes = set(scopes)
            
            if cached_scopes >= requested_scopes:  # Cached scopes include all requested scopes
                logger.info("Using cached credentials with sufficient scopes")
                return cached_credentials
            else:
                logger.info("Cached credentials don't have all requested scopes, re-authenticating")
        
        logger.info("Starting Google OAuth2 Device Code Flow...")
        
        # Step 1: Get device code
        device_response = await self._get_device_code(scopes)
        
        # Step 2: Display instructions to user
        self._display_user_instructions(device_response)
        
        # Step 3: Poll for token
        token_response = await self._poll_for_token(device_response)
        
        # Step 4: Create credentials object
        credentials = self._create_credentials(token_response)
        
        # Step 5: Cache the credentials
        self._save_credentials(credentials)
        
        logger.info("Authentication successful!")
        return credentials
    
    async def _get_device_code(self, scopes: list[str]) -> Dict[str, Any]:
        """Request device code from Google"""
        url = "https://oauth2.googleapis.com/device/code"
        
        data = {
            'client_id': self.client_config['client_id'],
            'scope': ' '.join(scopes)
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Failed to get device code: {response.status} - {error_text}")
                
                return await response.json()
    
    def _display_user_instructions(self, device_response: Dict[str, Any]):
        """Display instructions for user to complete authentication"""
        verification_url = device_response['verification_url']
        user_code = device_response['user_code']
        
        print("\n" + "="*60)
        print("GOOGLE OAUTH2 DEVICE CODE AUTHENTICATION")
        print("="*60)
        print(f"1. Open this URL in your browser:")
        print(f"   {verification_url}")
        print(f"\n2. Enter this code when prompted:")
        print(f"   {user_code}")
        print(f"\nWaiting for you to complete authentication...")
        print("="*60 + "\n")
        
        logger.info(f"User should visit {verification_url} and enter code: {user_code}")
    
    async def _poll_for_token(self, device_response: Dict[str, Any]) -> Dict[str, Any]:
        """Poll Google's token endpoint until user completes authentication"""
        url = "https://oauth2.googleapis.com/token"
        device_code = device_response['device_code']
        interval = device_response.get('interval', 5)  # Default to 5 seconds
        expires_in = device_response.get('expires_in', 1800)  # Default to 30 minutes
        
        data = {
            'client_id': self.client_config['client_id'],
            'client_secret': self.client_config['client_secret'],
            'device_code': device_code,
            'grant_type': 'urn:ietf:params:oauth:grant-type:device_code'
        }
        
        start_time = time.time()
        
        async with aiohttp.ClientSession() as session:
            while True:
                # Check if we've exceeded the timeout
                if time.time() - start_time > expires_in:
                    raise TimeoutError("Device code authentication timed out")
                
                async with session.post(url, data=data) as response:
                    response_data = await response.json()
                    
                    if response.status == 200:
                        # Success! We got the token
                        return response_data
                    
                    error = response_data.get('error')
                    
                    if error == 'authorization_pending':
                        # User hasn't completed authentication yet, keep polling
                        logger.debug("Authorization pending, continuing to poll...")
                        
                    elif error == 'slow_down':
                        # Google wants us to slow down our polling
                        interval += 5
                        logger.debug(f"Slowing down polling interval to {interval} seconds")
                        
                    elif error == 'expired_token':
                        raise Exception("Device code has expired. Please restart authentication.")
                        
                    elif error == 'access_denied':
                        raise Exception("User denied access to the application")
                        
                    else:
                        raise Exception(f"Authentication error: {error} - {response_data}")
                
                # Wait before polling again
                await asyncio.sleep(interval)
    
    def _create_credentials(self, token_response: Dict[str, Any]) -> Credentials:
        """Create Google Credentials object from token response"""
        return Credentials(
            token=token_response['access_token'],
            refresh_token=token_response.get('refresh_token'),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.client_config['client_id'],
            client_secret=self.client_config['client_secret'],
            scopes=token_response.get('scope', '').split()
        )


# Convenience function for easy usage
async def authenticate_with_device_code(credentials_file: str = 'credentials.json', 
                                      token_cache_file: str = 'token.pickle') -> Credentials:
    """
    Convenience function to perform device code authentication with caching
    
    Args:
        credentials_file: Path to credentials.json file
        token_cache_file: Path to cache file for storing tokens
        
    Returns:
        Google OAuth2 Credentials object
    """
    scopes = Config.SCOPES
    auth = DeviceCodeAuth(credentials_file, token_cache_file)
    result = await auth.authenticate(scopes)
    return result


# Example usage
async def main():
    """Example usage of the device code authentication"""
    scopes = [
        'https://www.googleapis.com/auth/drive.file',
        'https://www.googleapis.com/auth/drive'
    ]
    
    try:
        credentials = await authenticate_with_device_code(scopes)
        print(f"Successfully authenticated! Token: {credentials.token[:20]}...")
        
        # You can now use these credentials with googleapiclient
        from googleapiclient.discovery import build
        service = build('drive', 'v3', credentials=credentials)
        
        # Test the credentials
        results = service.files().list(pageSize=1).execute()
        print("Authentication test successful!")
        
    except Exception as e:
        print(f"Authentication failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
