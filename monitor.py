#!/usr/bin/env python3
"""
CDON Price Monitor and Web Dashboard
Run this script periodically to check prices and serve a web interface
"""

import asyncio
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, render_template_string, jsonify, request
from flask_cors import CORS
import json
from typing import List, Dict
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from pathlib import Path
import sys

# Import the main scraper
from cdon_scraper_v2 import CDONScraper

# Configuration from environment variables
CONFIG = {
    'check_interval_hours': int(os.environ.get('CHECK_INTERVAL_HOURS', 6)),
    'email_enabled': os.environ.get('EMAIL_ENABLED', 'false').lower() == 'true',
    'email_from': os.environ.get('EMAIL_FROM', ''),
    'email_to': os.environ.get('EMAIL_TO', ''),
    'email_password': os.environ.get('EMAIL_PASSWORD', ''),
    'smtp_server': os.environ.get('SMTP_SERVER', 'smtp.gmail.com'),
    'smtp_port': int(os.environ.get('SMTP_PORT', 587)),
    'discord_webhook': os.environ.get('DISCORD_WEBHOOK', None),
    'flask_host': os.environ.get('FLASK_HOST', '0.0.0.0'),
    'flask_port': int(os.environ.get('FLASK_PORT', 8080)),
    'flask_debug': os.environ.get('FLASK_DEBUG', 'false').lower() == 'true',
    'db_path': os.environ.get('DB_PATH', '/app/data/cdon_movies.db'),
}

# HTML Template for Web Dashboard
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CDON Blu-ray Price Tracker</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        h1 {
            color: white;
            text-align: center;
            margin-bottom: 30px;
            font-size: 2.5em;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            text-align: center;
        }
        .stat-card h3 {
            color: #667eea;
            font-size: 2em;
            margin-bottom: 5px;
        }
        .stat-card p {
            color: #666;
            font-size: 0.9em;
        }
        .section {
            background: white;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        h2 {
            color: #333;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 2px solid #667eea;
        }
        .search-box {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }
        .search-box input {
            flex: 1;
            padding: 10px;
            border: 2px solid #ddd;
            border-radius: 5px;
            font-size: 16px;
        }
        .search-box button {
            padding: 10px 30px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 16px;
            transition: background 0.3s;
        }
        .search-box button:hover {
            background: #5a67d8;
        }
        .movie-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 20px;
        }
        .movie-card {
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 15px;
            transition: transform 0.2s, box-shadow 0.2s;
            position: relative;
        }
        .movie-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }
        .movie-title {
            font-weight: bold;
            color: #333;
            margin-bottom: 8px;
        }
        .movie-format {
            display: inline-block;
            padding: 2px 8px;
            background: #667eea;
            color: white;
            border-radius: 3px;
            font-size: 0.8em;
            margin-bottom: 8px;
        }
        .price-info {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin: 10px 0;
        }
        .current-price {
            font-size: 1.4em;
            font-weight: bold;
            color: #28a745;
        }
        .price-change {
            font-size: 0.9em;
            padding: 2px 6px;
            border-radius: 3px;
        }
        .price-down {
            background: #d4edda;
            color: #155724;
        }
        .price-up {
            background: #f8d7da;
            color: #721c24;
        }
        .movie-link {
            display: inline-block;
            margin-top: 10px;
            color: #667eea;
            text-decoration: none;
        }
        .movie-link:hover {
            text-decoration: underline;
        }
        .alert {
            background: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 15px;
            margin-bottom: 15px;
            border-radius: 4px;
        }
        .alert-title {
            font-weight: bold;
            color: #856404;
            margin-bottom: 5px;
        }
        .watchlist-form {
            display: flex;
            gap: 10px;
            margin-top: 10px;
            padding-top: 10px;
            border-top: 1px solid #eee;
        }
        .watchlist-form input {
            padding: 5px;
            border: 1px solid #ddd;
            border-radius: 3px;
            width: 100px;
        }
        .watchlist-form button {
            padding: 5px 15px;
            background: #28a745;
            color: white;
            border: none;
            border-radius: 3px;
            cursor: pointer;
            font-size: 0.9em;
        }
        .ignore-button {
            padding: 5px 15px;
            background: #dc3545;
            color: white;
            border: none;
            border-radius: 3px;
            cursor: pointer;
            font-size: 0.9em;
            margin-top: 10px;
        }
        .ignore-button:hover {
            background: #c82333;
        }
        .price-history {
            margin-top: 10px;
            font-size: 0.85em;
            color: #666;
        }
        .loading {
            text-align: center;
            padding: 20px;
            color: #666;
        }
        
        /* Notification system */
        .notification-container {
            position: fixed;
            bottom: 20px;
            right: 20px;
            z-index: 9999;
            max-width: 350px;
        }
        
        .notification {
            background: #28a745;
            color: white;
            padding: 15px 20px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            margin-bottom: 10px;
            transform: translateX(400px);
            transition: transform 0.3s ease-in-out, opacity 0.3s ease-in-out;
            position: relative;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        
        .notification.show {
            transform: translateX(0);
        }
        
        .notification.error {
            background: #dc3545;
        }
        
        .notification.warning {
            background: #ffc107;
            color: #212529;
        }
        
        .notification.info {
            background: #17a2b8;
        }
        
        .notification-close {
            background: none;
            border: none;
            color: inherit;
            font-size: 18px;
            cursor: pointer;
            margin-left: 10px;
            opacity: 0.7;
        }
        
        .notification-close:hover {
            opacity: 1;
        }
        
        /* Remove from watchlist button */
        .remove-from-watchlist {
            position: absolute;
            top: 8px;
            right: 8px;
            background: #dc3545;
            color: white;
            border: none;
            border-radius: 50%;
            width: 24px;
            height: 24px;
            cursor: pointer;
            font-size: 14px;
            line-height: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            opacity: 0.7;
            transition: opacity 0.2s, background-color 0.2s;
        }
        
        .remove-from-watchlist:hover {
            opacity: 1;
            background: #c82333;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎬 CDON Blu-ray Price Tracker</h1>
        
        <div class="stats">
            <div class="stat-card">
                <h3 id="total-movies">-</h3>
                <p>Total Movies</p>
            </div>
            <div class="stat-card">
                <h3 id="price-drops">-</h3>
                <p>Price Drops Today</p>
            </div>
            <div class="stat-card">
                <h3 id="watchlist-count">-</h3>
                <p>Watchlist Items</p>
            </div>
            <div class="stat-card">
                <h3 id="last-update">-</h3>
                <p>Last Update</p>
            </div>
        </div>
        
        <div class="section">
            <h2>🔔 Recent Price Alerts</h2>
            <div id="alerts-container">
                <div class="loading">Loading alerts...</div>
            </div>
        </div>
        
        <div class="section">
            <h2>🔍 Search Movies</h2>
            <div class="search-box">
                <input type="text" id="search-input" placeholder="Search for movies..." onkeypress="if(event.key==='Enter') searchMovies()">
                <button onclick="searchMovies()">Search</button>
            </div>
            <div id="search-results" class="movie-grid"></div>
        </div>
        
        <div class="section">
            <h2>💰 Best Deals</h2>
            <div id="deals-container" class="movie-grid">
                <div class="loading">Loading deals...</div>
            </div>
        </div>
        
        <div class="section">
            <h2>👀 Watchlist</h2>
            <div id="watchlist-container" class="movie-grid">
                <div class="loading">Loading watchlist...</div>
            </div>
        </div>
        
        <div class="section">
            <h2>💵 Top 20 Cheapest Blu-rays</h2>
            <div id="cheapest-blurays-container" class="movie-grid">
                <div class="loading">Loading cheapest Blu-rays...</div>
            </div>
        </div>
        
        <div class="section">
            <h2>🎞️ Top 20 Cheapest 4K Blu-rays</h2>
            <div id="cheapest-4k-blurays-container" class="movie-grid">
                <div class="loading">Loading cheapest 4K Blu-rays...</div>
            </div>
        </div>
    </div>
    
    <script>
        // Load initial data
        window.addEventListener('load', () => {
            loadStats();
            loadAlerts();
            loadDeals();
            loadWatchlist();
            loadCheapestBlurays();
            loadCheapest4KBlurays();
        });
        
        async function loadStats() {
            const response = await fetch('/api/stats');
            const stats = await response.json();
            document.getElementById('total-movies').textContent = stats.total_movies;
            document.getElementById('price-drops').textContent = stats.price_drops_today;
            document.getElementById('watchlist-count').textContent = stats.watchlist_count;
            document.getElementById('last-update').textContent = new Date(stats.last_update).toLocaleString('fi-FI');
        }
        
        async function loadAlerts() {
            const response = await fetch('/api/alerts');
            const alerts = await response.json();
            const container = document.getElementById('alerts-container');
            
            if (alerts.length === 0) {
                container.innerHTML = '<p style="color: #666;">No recent price alerts</p>';
                return;
            }
            
            container.innerHTML = alerts.slice(0, 5).map(alert => `
                <div class="alert">
                    <div class="alert-title">${alert.title}</div>
                    <div>Price dropped from €${alert.old_price.toFixed(2)} to €${alert.new_price.toFixed(2)}</div>
                    <a href="${alert.url}" target="_blank" class="movie-link">View on CDON →</a>
                </div>
            `).join('');
        }
        
        async function loadDeals() {
            const response = await fetch('/api/deals');
            const deals = await response.json();
            const container = document.getElementById('deals-container');
            
            if (deals.length === 0) {
                container.innerHTML = '<p style="color: #666;">No deals found</p>';
                return;
            }
            
            container.innerHTML = deals.map(movie => createMovieCard(movie)).join('');
        }
        
        async function loadWatchlist() {
            const response = await fetch('/api/watchlist');
            const watchlist = await response.json();
            const container = document.getElementById('watchlist-container');
            
            if (watchlist.length === 0) {
                container.innerHTML = '<p style="color: #666;">Watchlist is empty</p>';
                return;
            }
            
            container.innerHTML = watchlist.map(item => createMovieCard(item, true)).join('');
        }
        
        async function searchMovies() {
            const query = document.getElementById('search-input').value;
            if (!query) return;
            
            const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
            const movies = await response.json();
            const container = document.getElementById('search-results');
            
            if (movies.length === 0) {
                container.innerHTML = '<p style="color: #666;">No movies found</p>';
                return;
            }
            
            container.innerHTML = movies.map(movie => createMovieCard(movie)).join('');
        }
        
        async function loadCheapestBlurays() {
            const response = await fetch('/api/cheapest-blurays');
            const movies = await response.json();
            const container = document.getElementById('cheapest-blurays-container');
            
            if (movies.length === 0) {
                container.innerHTML = '<p style="color: #666;">No Blu-rays found</p>';
                return;
            }
            
            container.innerHTML = movies.map(movie => createMovieCard(movie, false, true)).join('');
        }
        
        async function loadCheapest4KBlurays() {
            const response = await fetch('/api/cheapest-4k-blurays');
            const movies = await response.json();
            const container = document.getElementById('cheapest-4k-blurays-container');
            
            if (movies.length === 0) {
                container.innerHTML = '<p style="color: #666;">No 4K Blu-rays found</p>';
                return;
            }
            
            container.innerHTML = movies.map(movie => createMovieCard(movie, false, true)).join('');
        }

        function createMovieCard(movie, showTarget = false, showIgnore = false) {
            const priceChange = movie.price_change || 0;
            const priceClass = priceChange < 0 ? 'price-down' : priceChange > 0 ? 'price-up' : '';
            const priceSymbol = priceChange < 0 ? '↓' : priceChange > 0 ? '↑' : '';
            
            return `
                <div class="movie-card" id="movie-card-${movie.id}">
                    ${showTarget ? `<button class="remove-from-watchlist" onclick="removeFromWatchlist(${movie.id})" title="Remove from watchlist">×</button>` : ''}
                    <div class="movie-title">${movie.title}</div>
                    <span class="movie-format">${movie.format}</span>
                    <div class="price-info">
                        <span class="current-price">€${movie.current_price ? movie.current_price.toFixed(2) : '-'}</span>
                        ${priceChange !== 0 ? `<span class="price-change ${priceClass}">${priceSymbol} €${Math.abs(priceChange).toFixed(2)}</span>` : ''}
                    </div>
                    ${movie.lowest_price ? `
                        <div class="price-history">
                            Lowest: €${movie.lowest_price.toFixed(2)} | Highest: €${movie.highest_price.toFixed(2)}
                        </div>
                    ` : ''}
                    ${showTarget && movie.target_price ? `
                        <div style="color: #666; font-size: 0.9em; margin-top: 5px;">
                            Target: €${movie.target_price.toFixed(2)}
                        </div>
                    ` : ''}
                    ${!showTarget ? `
                        <div class="watchlist-form">
                            <input type="number" step="0.01" placeholder="Target €" id="target-${movie.id}">
                            <button onclick="addToWatchlist(${movie.id})">Add to Watchlist</button>
                        </div>
                    ` : ''}
                    ${showIgnore ? `<button class="ignore-button" onclick="ignoreMovie(${movie.id})">Ignore</button>` : ''}
                    <a href="${movie.url}" target="_blank" class="movie-link">View on CDON →</a>
                </div>
            `;
        }
        
        async function addToWatchlist(movieId) {
            const targetPrice = document.getElementById(`target-${movieId}`).value;
            if (!targetPrice) {
                showNotification('Please enter a target price', 'warning');
                return;
            }
            
            const response = await fetch('/api/watchlist', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({movie_id: movieId, target_price: parseFloat(targetPrice)})
            });
            
            if (response.ok) {
                showNotification('Added to watchlist!');
                loadWatchlist();
                loadStats();
            }
        }

        async function removeFromWatchlist(movieId) {
            if (!confirm('Remove this movie from your watchlist?')) {
                return;
            }
            
            const response = await fetch(`/api/watchlist/${movieId}`, {
                method: 'DELETE'
            });
            
            if (response.ok) {
                // Remove the movie card from the watchlist view
                const movieCard = document.getElementById(`movie-card-${movieId}`);
                if (movieCard) {
                    movieCard.remove();
                }
                showNotification('Removed from watchlist');
                loadStats(); // Update the watchlist count
            } else {
                showNotification('Failed to remove from watchlist', 'error');
            }
        }

        async function ignoreMovie(movieId) {
            if (!confirm('Are you sure you want to ignore this movie? It will be removed from cheapest views.')) {
                return;
            }
            
            const response = await fetch('/api/ignore-movie', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({movie_id: movieId})
            });
            
            if (response.ok) {
                // Remove the movie card from the view
                const movieCard = document.getElementById(`movie-card-${movieId}`);
                if (movieCard) {
                    movieCard.remove();
                }
                showNotification('Movie ignored and removed from cheapest views');
            }
        }
        
        // Notification system
        function showNotification(message, type = 'success', duration = 4000) {
            // Create notification container if it doesn't exist
            let container = document.querySelector('.notification-container');
            if (!container) {
                container = document.createElement('div');
                container.className = 'notification-container';
                document.body.appendChild(container);
            }
            
            // Create notification element
            const notification = document.createElement('div');
            notification.className = `notification ${type}`;
            
            const messageSpan = document.createElement('span');
            messageSpan.textContent = message;
            
            const closeBtn = document.createElement('button');
            closeBtn.className = 'notification-close';
            closeBtn.innerHTML = '×';
            closeBtn.onclick = () => hideNotification(notification);
            
            notification.appendChild(messageSpan);
            notification.appendChild(closeBtn);
            container.appendChild(notification);
            
            // Show notification with animation
            setTimeout(() => notification.classList.add('show'), 10);
            
            // Auto-hide after duration
            setTimeout(() => hideNotification(notification), duration);
        }
        
        function hideNotification(notification) {
            notification.classList.remove('show');
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.parentNode.removeChild(notification);
                }
            }, 300);
        }
    </script>
    
    <!-- Notification container will be added dynamically -->
</body>
</html>
'''

class PriceMonitor:
    """Monitor prices and send notifications"""
    
    def __init__(self, scraper: CDONScraper):
        self.scraper = scraper
        self.db_path = scraper.db_path
    
    async def check_watchlist_prices(self):
        """Check prices for all watchlist items"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get all watchlist items with their URLs
        cursor.execute('''
            SELECT w.*, m.url, m.title 
            FROM watchlist w
            JOIN movies m ON w.movie_id = m.id
        ''')
        
        watchlist_items = cursor.fetchall()
        conn.close()
        
        if not watchlist_items:
            print("No items in watchlist")
            return
        
        print(f"Checking {len(watchlist_items)} watchlist items...")
        
        # Create browser and check each item
        browser, context, page = await self.scraper.create_browser()
        
        for item in watchlist_items:
            movie_id, _, target_price, _, _, url, title = item
            print(f"Checking: {title}")
            
            try:
                # Scrape the specific product page
                movies = await self.scraper.scrape_page(page, url)
                if movies:
                    self.scraper.save_movies(movies)
                    
                # Small delay between requests
                await asyncio.sleep(2)
                
            except Exception as e:
                print(f"Error checking {title}: {e}")
        
        await browser.close()
        
        # Get and process alerts
        alerts = self.scraper.get_price_alerts()
        if alerts:
            await self.send_notifications(alerts)
            self.scraper.mark_alerts_notified([a['id'] for a in alerts])
    
    async def send_notifications(self, alerts: List[Dict]):
        """Send email/Discord notifications for price alerts"""
        if not alerts:
            return
        
        # Console output (always enabled)
        print("\n" + "="*50)
        print("🎉 PRICE ALERTS!")
        print("="*50)
        for alert in alerts:
            if alert['alert_type'] == 'price_drop':
                print(f"📉 {alert['title']}")
                print(f"   Price dropped: €{alert['old_price']} → €{alert['new_price']}")
            elif alert['alert_type'] == 'target_reached':
                print(f"🎯 {alert['title']}")
                print(f"   Target price reached: €{alert['new_price']}")
            print(f"   View: {alert['url']}\n")
        
        # Email notification
        if CONFIG['email_enabled']:
            self.send_email_notification(alerts)
        
        # Discord webhook
        if CONFIG['discord_webhook']:
            await self.send_discord_notification(alerts)
    
    def send_email_notification(self, alerts: List[Dict]):
        """Send email notification"""
        try:
            msg = MIMEMultipart()
            msg['From'] = CONFIG['email_from']
            msg['To'] = CONFIG['email_to']
            msg['Subject'] = f'CDON Price Alerts - {len(alerts)} new alerts!'
            
            body = "New price alerts from CDON:\n\n"
            for alert in alerts:
                body += f"📽️ {alert['title']}\n"
                body += f"Price: €{alert['old_price']} → €{alert['new_price']}\n"
                body += f"Link: {alert['url']}\n\n"
            
            msg.attach(MIMEText(body, 'plain'))
            
            server = smtplib.SMTP(CONFIG['smtp_server'], CONFIG['smtp_port'])
            server.starttls()
            server.login(CONFIG['email_from'], CONFIG['email_password'])
            server.send_message(msg)
            server.quit()
            
            print("✅ Email notification sent")
        except Exception as e:
            print(f"❌ Failed to send email: {e}")
    
    async def send_discord_notification(self, alerts: List[Dict]):
        """Send Discord webhook notification"""
        import aiohttp
        
        for alert in alerts:
            embed = {
                "title": alert['title'],
                "description": f"Price: €{alert['old_price']} → €{alert['new_price']}",
                "url": alert['url'],
                "color": 0x00ff00 if alert['alert_type'] == 'price_drop' else 0x0099ff
            }
            
            async with aiohttp.ClientSession() as session:
                await session.post(CONFIG['discord_webhook'], json={"embeds": [embed]})

# Flask Web Application
app = Flask(__name__)
CORS(app)

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/stats')
def api_stats():
    conn = sqlite3.connect(CONFIG['db_path'])
    cursor = conn.cursor()
    
    # Get statistics
    cursor.execute('SELECT COUNT(*) FROM movies')
    total_movies = cursor.fetchone()[0]
    
    cursor.execute('''
        SELECT COUNT(*) FROM price_alerts 
        WHERE DATE(created_at) = DATE('now')
    ''')
    price_drops_today = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM watchlist')
    watchlist_count = cursor.fetchone()[0]
    
    cursor.execute('SELECT MAX(last_updated) FROM movies')
    last_update = cursor.fetchone()[0]
    
    conn.close()
    
    return jsonify({
        'total_movies': total_movies,
        'price_drops_today': price_drops_today,
        'watchlist_count': watchlist_count,
        'last_update': last_update
    })

@app.route('/api/alerts')
def api_alerts():
    scraper = CDONScraper(CONFIG['db_path'])
    alerts = scraper.get_price_alerts()
    return jsonify(alerts[:10])  # Return last 10 alerts

@app.route('/api/deals')
def api_deals():
    conn = sqlite3.connect(CONFIG['db_path'])
    cursor = conn.cursor()
    
    # Get movies with biggest price drops
    cursor.execute('''
        SELECT m.*, 
               ph1.price as current_price,
               ph2.price as previous_price,
               (ph2.price - ph1.price) as price_change,
               (SELECT MIN(price) FROM price_history WHERE movie_id = m.id) as lowest_price,
               (SELECT MAX(price) FROM price_history WHERE movie_id = m.id) as highest_price
        FROM movies m
        JOIN price_history ph1 ON m.id = ph1.movie_id
        LEFT JOIN price_history ph2 ON m.id = ph2.movie_id AND ph2.id < ph1.id
        WHERE ph1.id = (SELECT MAX(id) FROM price_history WHERE movie_id = m.id)
        AND ph2.id = (SELECT MAX(id) FROM price_history WHERE movie_id = m.id AND id < ph1.id)
        AND ph1.price < ph2.price
        ORDER BY (ph2.price - ph1.price) ASC
        LIMIT 12
    ''')
    
    deals = []
    for row in cursor.fetchall():
        deals.append({
            'id': row[0],
            'title': row[2],
            'format': row[3],
            'url': row[4],
            'current_price': row[8],
            'previous_price': row[9],
            'price_change': row[10],
            'lowest_price': row[11],
            'highest_price': row[12]
        })
    
    conn.close()
    return jsonify(deals)

@app.route('/api/watchlist')
def api_watchlist():
    conn = sqlite3.connect(CONFIG['db_path'])
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT m.*, w.target_price,
               (SELECT price FROM price_history WHERE movie_id = m.id ORDER BY checked_at DESC LIMIT 1) as current_price,
               (SELECT MIN(price) FROM price_history WHERE movie_id = m.id) as lowest_price,
               (SELECT MAX(price) FROM price_history WHERE movie_id = m.id) as highest_price
        FROM watchlist w
        JOIN movies m ON w.movie_id = m.id
    ''')
    
    watchlist = []
    for row in cursor.fetchall():
        watchlist.append({
            'id': row[0],
            'title': row[2],
            'format': row[3],
            'url': row[4],
            'target_price': row[8],
            'current_price': row[9],
            'lowest_price': row[10],
            'highest_price': row[11]
        })
    
    conn.close()
    return jsonify(watchlist)

@app.route('/api/watchlist', methods=['POST'])
def api_add_watchlist():
    data = request.json
    conn = sqlite3.connect(CONFIG['db_path'])
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO watchlist (movie_id, target_price)
        VALUES (?, ?)
    ''', (data['movie_id'], data['target_price']))
    
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/watchlist/<int:movie_id>', methods=['DELETE'])
def api_remove_watchlist(movie_id):
    conn = sqlite3.connect(CONFIG['db_path'])
    cursor = conn.cursor()
    
    cursor.execute('''
        DELETE FROM watchlist WHERE movie_id = ?
    ''', (movie_id,))
    
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/search')
def api_search():
    query = request.args.get('q', '')
    scraper = CDONScraper(CONFIG['db_path'])
    results = scraper.search_movies(query)
    return jsonify(results)

@app.route('/api/cheapest-blurays')
def api_cheapest_blurays():
    conn = sqlite3.connect(CONFIG['db_path'])
    cursor = conn.cursor()
    
    # Get top 20 cheapest regular Blu-rays (not ignored and not in watchlist)
    cursor.execute('''
        SELECT m.*, 
               (SELECT price FROM price_history WHERE movie_id = m.id ORDER BY checked_at DESC LIMIT 1) as current_price,
               (SELECT MIN(price) FROM price_history WHERE movie_id = m.id) as lowest_price,
               (SELECT MAX(price) FROM price_history WHERE movie_id = m.id) as highest_price
        FROM movies m
        WHERE m.id NOT IN (SELECT movie_id FROM ignored_movies)
        AND m.id NOT IN (SELECT movie_id FROM watchlist)
        AND (m.format LIKE '%Blu-ray%' AND m.format NOT LIKE '%4K%' AND m.format NOT LIKE '%Ultra HD%')
        AND EXISTS (SELECT 1 FROM price_history WHERE movie_id = m.id)
        ORDER BY (SELECT price FROM price_history WHERE movie_id = m.id ORDER BY checked_at DESC LIMIT 1) ASC
        LIMIT 20
    ''')
    
    movies = []
    for row in cursor.fetchall():
        movies.append({
            'id': row[0],
            'title': row[2],
            'format': row[3],
            'url': row[4],
            'current_price': row[8],
            'lowest_price': row[9],
            'highest_price': row[10]
        })
    
    conn.close()
    return jsonify(movies)

@app.route('/api/cheapest-4k-blurays')
def api_cheapest_4k_blurays():
    conn = sqlite3.connect(CONFIG['db_path'])
    cursor = conn.cursor()
    
    # Get top 20 cheapest 4K Blu-rays (not ignored and not in watchlist)
    cursor.execute('''
        SELECT m.*, 
               (SELECT price FROM price_history WHERE movie_id = m.id ORDER BY checked_at DESC LIMIT 1) as current_price,
               (SELECT MIN(price) FROM price_history WHERE movie_id = m.id) as lowest_price,
               (SELECT MAX(price) FROM price_history WHERE movie_id = m.id) as highest_price
        FROM movies m
        WHERE m.id NOT IN (SELECT movie_id FROM ignored_movies)
        AND m.id NOT IN (SELECT movie_id FROM watchlist)
        AND (m.format LIKE '%4K%' OR m.format LIKE '%Ultra HD%')
        AND EXISTS (SELECT 1 FROM price_history WHERE movie_id = m.id)
        ORDER BY (SELECT price FROM price_history WHERE movie_id = m.id ORDER BY checked_at DESC LIMIT 1) ASC
        LIMIT 20
    ''')
    
    movies = []
    for row in cursor.fetchall():
        movies.append({
            'id': row[0],
            'title': row[2],
            'format': row[3],
            'url': row[4],
            'current_price': row[8],
            'lowest_price': row[9],
            'highest_price': row[10]
        })
    
    conn.close()
    return jsonify(movies)

@app.route('/api/ignore-movie', methods=['POST'])
def api_ignore_movie():
    data = request.json
    conn = sqlite3.connect(CONFIG['db_path'])
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR IGNORE INTO ignored_movies (movie_id)
        VALUES (?)
    ''', (data['movie_id'],))
    
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/unignore-movie', methods=['POST'])
def api_unignore_movie():
    data = request.json
    conn = sqlite3.connect(CONFIG['db_path'])
    cursor = conn.cursor()
    
    cursor.execute('''
        DELETE FROM ignored_movies WHERE movie_id = ?
    ''', (data['movie_id'],))
    
    conn.commit()
    conn.close()
    return jsonify({'success': True})

async def run_monitor():
    """Run the price monitor"""
    scraper = CDONScraper(CONFIG['db_path'])
    monitor = PriceMonitor(scraper)
    
    while True:
        print(f"\n🔄 Starting price check at {datetime.now()}")
        await monitor.check_watchlist_prices()
        
        print(f"✅ Check complete. Next check in {CONFIG['check_interval_hours']} hours")
        await asyncio.sleep(CONFIG['check_interval_hours'] * 3600)

def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == 'monitor':
            # Run price monitor
            print("Starting price monitor...")
            asyncio.run(run_monitor())
        elif sys.argv[1] == 'web':
            # Run web server
            print(f"Starting web dashboard on http://{CONFIG['flask_host']}:{CONFIG['flask_port']}")
            app.run(host=CONFIG['flask_host'], port=CONFIG['flask_port'], debug=CONFIG['flask_debug'])
        elif sys.argv[1] == 'crawl':
            # Run initial crawl
            async def crawl():
                scraper = CDONScraper(CONFIG['db_path'])
                max_pages = int(os.environ.get('MAX_PAGES_PER_CATEGORY', 10))
                await scraper.crawl_category("https://cdon.fi/elokuvat/?facets=property_preset_media_format%3Ablu-ray&q=", max_pages=max_pages)
                await scraper.crawl_category("https://cdon.fi/elokuvat/?facets=property_preset_media_format%3A4k%20ultra%20hd&q=", max_pages=max_pages)
            asyncio.run(crawl())
    else:
        print("""
CDON Blu-ray Price Tracker
Usage:
    python monitor.py crawl    - Initial crawl of CDON
    python monitor.py monitor  - Run price monitor (checks every 6 hours)
    python monitor.py web      - Start web dashboard
        """)

if __name__ == "__main__":
    main()
