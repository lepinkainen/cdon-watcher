// Load initial data
window.addEventListener('load', () => {
  loadStats()
  loadAlerts()
  loadDeals()
  loadWatchlist()
  loadCheapestBlurays()
  loadCheapest4KBlurays()
})

async function loadStats() {
  const response = await fetch('/api/stats')
  const stats = await response.json()
  document.getElementById('total-movies').textContent = stats.total_movies
  document.getElementById('price-drops').textContent = stats.price_drops_today
  document.getElementById('watchlist-count').textContent = stats.watchlist_count
  document.getElementById('last-update').textContent = new Date(
    stats.last_update
  ).toLocaleString('fi-FI')
}

async function loadAlerts() {
  const response = await fetch('/api/alerts')
  const alerts = await response.json()
  const container = document.getElementById('alerts-container')

  if (alerts.length === 0) {
    container.innerHTML = '<p style="color: #666;">No recent price alerts</p>'
    return
  }

  container.innerHTML = alerts
    .slice(0, 5)
    .map(
      (alert) => `
        <div class="alert">
            <div class="alert-title">${alert.title}</div>
            <div>Price dropped from €${alert.old_price.toFixed(
              2
            )} to €${alert.new_price.toFixed(2)}</div>
            <a href="${
              alert.url
            }" target="_blank" class="movie-link">View on CDON →</a>
        </div>
    `
    )
    .join('')
}

async function loadDeals() {
  const response = await fetch('/api/deals')
  const deals = await response.json()
  const container = document.getElementById('deals-container')
  const section = container.closest('.section')

  if (deals.length === 0) {
    section.style.display = 'none'
    return
  }

  section.style.display = 'block'
  container.innerHTML = deals.map((movie) => createMovieCard(movie)).join('')
}

async function loadWatchlist() {
  const response = await fetch('/api/watchlist')
  const watchlist = await response.json()
  const container = document.getElementById('watchlist-container')

  if (watchlist.length === 0) {
    container.innerHTML = '<p style="color: #666;">Watchlist is empty</p>'
    return
  }

  container.innerHTML = watchlist
    .map((item) => createMovieCard(item, true))
    .join('')
}

async function searchMovies() {
  const query = document.getElementById('search-input').value
  if (!query) return

  const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`)
  const movies = await response.json()
  const container = document.getElementById('search-results')

  if (movies.length === 0) {
    container.innerHTML = '<p style="color: #666;">No movies found</p>'
    return
  }

  container.innerHTML = movies.map((movie) => createMovieCard(movie)).join('')
}

async function loadCheapestBlurays() {
  const response = await fetch('/api/cheapest-blurays')
  const movies = await response.json()
  const container = document.getElementById('cheapest-blurays-container')

  if (movies.length === 0) {
    container.innerHTML = '<p style="color: #666;">No Blu-rays found</p>'
    return
  }

  container.innerHTML = movies
    .map((movie) => createMovieCard(movie, false, true))
    .join('')
}

async function loadCheapest4KBlurays() {
  const response = await fetch('/api/cheapest-4k-blurays')
  const movies = await response.json()
  const container = document.getElementById('cheapest-4k-blurays-container')

  if (movies.length === 0) {
    container.innerHTML = '<p style="color: #666;">No 4K Blu-rays found</p>'
    return
  }

  container.innerHTML = movies
    .map((movie) => createMovieCard(movie, false, true))
    .join('')
}

function createMovieCard(movie, showTarget = false, showIgnore = false) {
  const priceChange = movie.price_change || 0
  const priceClass =
    priceChange < 0 ? 'price-down' : priceChange > 0 ? 'price-up' : ''
  const priceSymbol = priceChange < 0 ? '↓' : priceChange > 0 ? '↑' : ''

  // Create poster image HTML
  let posterHtml = ''
  if (movie.image_url && movie.tmdb_id) {
    // Local poster from TMDB
    const posterFilename = `${movie.tmdb_id}.jpg`
    posterHtml = `<div class="movie-poster">
            <img src="/posters/${posterFilename}" alt="${movie.title} poster" 
                 onerror="this.style.display='none'; this.parentElement.classList.add('no-poster');">
        </div>`
  } else if (movie.image_url) {
    // Original CDON image
    posterHtml = `<div class="movie-poster">
            <img src="${movie.image_url}" alt="${movie.title} poster"
                 onerror="this.style.display='none'; this.parentElement.classList.add('no-poster');">
        </div>`
  } else {
    // No poster available
    posterHtml = `<div class="movie-poster no-poster">
            <div class="poster-placeholder">🎬</div>
        </div>`
  }

  return `
        <div class="movie-card" id="movie-card-${movie.id}" data-product-id="${
          movie.product_id
        }">
            ${
              showTarget
                ? `<button class="remove-from-watchlist" onclick="removeFromWatchlist('${movie.product_id}')" title="Remove from watchlist">×</button>`
                : ''
            }
            ${posterHtml}
            <div class="movie-info">
                <div class="movie-title">${movie.title}</div>
                <span class="movie-format">${movie.format}</span>
                <div class="price-info">
                    <span class="current-price">€${
                      movie.current_price ? movie.current_price.toFixed(2) : '-'
                    }</span>
                    ${
                      priceChange !== 0
                        ? `<span class="price-change ${priceClass}">${priceSymbol} €${Math.abs(
                            priceChange
                          ).toFixed(2)}</span>`
                        : ''
                    }
                </div>
                ${
                  movie.lowest_price
                    ? `
                    <div class="price-history">
                        Lowest: €${movie.lowest_price.toFixed(
                          2
                        )} | Highest: €${movie.highest_price.toFixed(2)}
                    </div>
                `
                    : ''
                }
                ${
                  showTarget && movie.target_price
                    ? `
                    <div style="color: #666; font-size: 0.9em; margin-top: 5px;">
                        Target: €${movie.target_price.toFixed(2)}
                    </div>
                `
                    : ''
                }
                ${
                  !showTarget
                    ? `
                    <div class="watchlist-form">
                        <input type="number" step="0.01" placeholder="Target €" id="target-${movie.id}">
                        <button onclick="addToWatchlist(${movie.id})">Add to Watchlist</button>
                    </div>
                `
                    : ''
                }
                ${
                  showIgnore
                    ? `<button class="ignore-button" onclick="ignoreMovie('${movie.product_id}')">Ignore</button>`
                    : ''
                }
                <a href="${
                  movie.url
                }" target="_blank" class="movie-link">View on CDON →</a>
            </div>
        </div>
    `
}

async function addToWatchlist(movieId) {
  const targetPrice = document.getElementById(`target-${movieId}`).value
  if (!targetPrice) {
    showNotification('Please enter a target price', 'warning')
    return
  }

  const movieCard = document.getElementById(`movie-card-${movieId}`)
  const productId = movieCard.getAttribute('data-product-id')

  const response = await fetch('/api/watchlist', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      product_id: productId,
      target_price: parseFloat(targetPrice),
    }),
  })

  if (response.ok) {
    showNotification('Added to watchlist!')
    loadWatchlist()
    loadStats()
  } else {
    const errorData = await response.json()
    showNotification(
      `Failed to add to watchlist: ${errorData.detail || 'Unknown error'}`,
      'error'
    )
  }
}

async function removeFromWatchlist(productId) {
  if (!confirm('Remove this movie from your watchlist?')) {
    return
  }

  const response = await fetch(`/api/watchlist/${productId}`, {
    method: 'DELETE',
  })

  if (response.ok) {
    // Remove the movie card from the watchlist view by finding it using product_id
    const movieCard = document.querySelector(`[data-product-id="${productId}"]`)
    if (movieCard) {
      movieCard.remove()
    }
    showNotification('Removed from watchlist')
    loadStats() // Update the watchlist count
    loadWatchlist() // Refresh the watchlist view
  } else {
    const errorData = await response.json()
    showNotification(
      `Failed to remove from watchlist: ${errorData.detail || 'Unknown error'}`,
      'error'
    )
  }
}

async function ignoreMovie(productId) {
  if (
    !confirm(
      'Are you sure you want to ignore this movie? It will be removed from cheapest views.'
    )
  ) {
    return
  }

  const response = await fetch('/api/ignore-movie', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ product_id: productId }),
  })

  if (response.ok) {
    // Remove all movie cards with this product_id from the view
    const movieCards = document.querySelectorAll(
      `[data-product-id="${productId}"]`
    )
    movieCards.forEach((card) => card.remove())

    // Also try to find cards by checking all movie cards (fallback)
    const allCards = document.querySelectorAll('.movie-card')
    allCards.forEach((card) => {
      const cardButton = card.querySelector('.ignore-button')
      if (
        cardButton &&
        cardButton.getAttribute('onclick').includes(`'${productId}'`)
      ) {
        card.remove()
      }
    })

    showNotification('Movie ignored and removed from cheapest views')
  } else {
    showNotification('Failed to ignore movie', 'error')
  }
}

// Notification system
function showNotification(message, type = 'success', duration = 4000) {
  // Create notification container if it doesn't exist
  let container = document.querySelector('.notification-container')
  if (!container) {
    container = document.createElement('div')
    container.className = 'notification-container'
    document.body.appendChild(container)
  }

  // Create notification element
  const notification = document.createElement('div')
  notification.className = `notification ${type}`

  const messageSpan = document.createElement('span')
  messageSpan.textContent = message

  const closeBtn = document.createElement('button')
  closeBtn.className = 'notification-close'
  closeBtn.innerHTML = '×'
  closeBtn.onclick = () => hideNotification(notification)

  notification.appendChild(messageSpan)
  notification.appendChild(closeBtn)
  container.appendChild(notification)

  // Show notification with animation
  setTimeout(() => notification.classList.add('show'), 10)

  // Auto-hide after duration
  setTimeout(() => hideNotification(notification), duration)
}

function hideNotification(notification) {
  notification.classList.remove('show')
  setTimeout(() => {
    if (notification.parentNode) {
      notification.parentNode.removeChild(notification)
    }
  }, 300)
}
