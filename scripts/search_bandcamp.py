#!/usr/bin/env python3
"""
Search Bandcamp for single-track albums from hominiscanidae archive.
Outputs: singles_from_bandcamp.csv with slug, bandcamp_url, num_tracks
"""

import json
import csv
import re
import time
import urllib.parse
from collections import defaultdict

from ddgs import DDGS
import requests
from bs4 import BeautifulSoup

def slug_to_search_term(slug):
    """Convert our slug to a search term (artist name)."""
    # Remove year prefix and extra year suffix
    parts = slug.split('-')
    
    # Skip leading year (4 digits starting with 19 or 20)
    year_pattern = re.compile(r'^(19|20)\d{2}$')
    
    search_parts = []
    skip_count = 0
    for i, part in enumerate(parts):
        if i == 0 and year_pattern.match(part):
            continue  # Skip leading year
        # Skip trailing year duplication like "2004" at end
        if i >= len(parts) - 1 and year_pattern.match(part):
            continue
        search_parts.append(part)
    
    # Take first 5 parts max to keep search focused
    term = ' '.join(search_parts[:5])
    return term if term else slug

def extract_artist_from_slug(slug):
    """Extract artist name from slug - conservative approach."""
    # Remove .mp3 extension
    clean = re.sub(r'\.mp3$', '', slug)
    parts = clean.split('-')
    year_pattern = re.compile(r'^(19|20)\d{2}$')
    
    # Skip leading year
    start = 1 if (parts and year_pattern.match(parts[0])) else 0
    
    # Skip trailing year/duplicates (stop at first year-like suffix)
    end = len(parts)
    for i in range(len(parts) - 1, start, -1):
        if year_pattern.match(parts[i]):
            end = i
            break
    
    # Join and clean up
    result = ' '.join(parts[start:end])
    return result if result else None

def count_bandcamp_tracks(url, session):
    """Count tracks on a Bandcamp album page."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        r = session.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Count /track/ links within the album section
        # Bandcamp album pages have track links in a specific structure
        track_links = soup.find_all('a', href=re.compile(r'/track/'))
        
        # Alternative: look for meta numTracks
        meta = soup.find('meta', itemprop='numTracks')
        if meta:
            try:
                return int(meta.get('content', 0))
            except:
                pass
        
        # Alternative: count from JSON data
        import re as re2
        # Look for album track count in the page's data structure
        matches = re2.findall(r'"num_tracks"\s*:\s*(\d+)', r.text)
        if matches:
            return int(matches[0])
        
        # Fallback: count track links
        return len(track_links) if track_links else 1
        
    except Exception as e:
        return None

def search_bandcamp(artist_name, session):
    """Search for artist on Bandcamp and return first result URL."""
    try:
        with DDGS() as ddgs:
            # Search for "artist name site:bandcamp.com"
            query = f'"{artist_name}" site:bandcamp.com'
            for result in ddgs.text(query, max_results=3):
                href = result.get('href', '')
                if 'bandcamp.com' in href:
                    # Extract clean URL (could be artist or album page)
                    return href
        return None
    except Exception as e:
        print(f"Search error for {artist_name}: {e}")
        return None

def main():
    # Load albums
    with open('data/homi-albums.json') as f:
        albums = json.load(f)
    
    # Filter single-track albums
    single_track = [a for a in albums if len(a.get('tracks', [])) == 1]
    print(f"Processing {len(single_track)} single-track albums...")
    
    results = []
    session = requests.Session()
    
    for i, album in enumerate(single_track):
        slug = album['id']
        # Use stored artist if available, otherwise extract from slug
        artist_name = album.get('artist', '').strip()
        if not artist_name:
            artist_name = extract_artist_from_slug(slug)
        
        if i % 50 == 0:
            print(f"Progress: {i}/{len(single_track)} - {artist_name}")
        
        # Try to find Bandcamp page
        bandcamp_url = search_bandcamp(artist_name, session)
        
        if bandcamp_url:
            # Try to get track count if it's an album page
            num_tracks = None
            if '/album/' in bandcamp_url:
                num_tracks = count_bandcamp_tracks(bandcamp_url, session)
            
            results.append({
                'slug': slug,
                'artist': artist_name or '',
                'bandcamp_url': bandcamp_url,
                'num_tracks': num_tracks if num_tracks else ''
            })
        else:
            results.append({
                'slug': slug,
                'artist': artist_name or '',
                'bandcamp_url': '',
                'num_tracks': ''
            })
        
        # Rate limit to avoid getting blocked
        time.sleep(0.5)
    
    # Write CSV
    with open('singles_from_bandcamp.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['slug', 'artist', 'bandcamp_url', 'num_tracks'])
        writer.writeheader()
        writer.writerows(results)
    
    # Summary
    found = sum(1 for r in results if r['bandcamp_url'])
    print(f"\nDone! Found {found}/{len(results)} on Bandcamp")
    print(f"Saved to singles_from_bandcamp.csv")

if __name__ == '__main__':
    main()