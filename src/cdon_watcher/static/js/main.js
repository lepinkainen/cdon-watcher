// Load initial data
window.addEventListener('load', () => {
  loadStats()
  loadAlerts()
  loadDeals()
  loadWatchlist()
  loadCheapestBlurays()
  loadCheapest4KBlurays()
  loadBoxSets()
  loadBoxSetWatchlist()
  loadMatchQueueBadge()
})

async function loadMatchQueueBadge() {
  try {
    const response = await fetch('/api/match/queue?offset=0')
    const data = await response.json()
    const badge = document.getElementById('match-queue-badge')
    if (badge) {
      if (data.total > 0) {
        badge.textContent = data.total
        badge.style.display = 'inline-block'
      } else {
        badge.style.display = 'none'
      }
    }
  } catch (error) {
    console.error('Failed to load match queue badge:', error)
  }
}

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
    .map((item) => createWatchlistCard(item))
    .join('')
}

function createWatchlistCard(item) {
  const tmdb = item.tmdb_movie
  const versions = item.versions || []
  const targetPrice = item.target_price

  // Create poster HTML using TMDB poster
  let posterHtml = ''
  if (tmdb.poster_path) {
    const posterFilename = `${tmdb.tmdb_id}.jpg`
    posterHtml = `<div class="movie-poster">
      <img src="/posters/${posterFilename}" alt="${tmdb.title} poster"
           onerror="this.style.display='none'; this.parentElement.classList.add('no-poster');">
    </div>`
  } else {
    posterHtml = `<div class="movie-poster no-poster">
      <div class="poster-placeholder">🎬</div>
    </div>`
  }

  // Create versions list (all formats)
  const versionsHtml = versions
    .map((v) => {
      const priceInfo = v.current_price
        ? `€${v.current_price.toFixed(2)}`
        : 'N/A'
      const atTarget = v.current_price && v.current_price <= targetPrice
      return `<div class="watchlist-version ${atTarget ? 'at-target' : ''}">
      <span class="version-format">${v.format || 'Unknown'}</span>
      <span class="version-price">${priceInfo}</span>
      ${atTarget ? '<span class="target-reached">✓ Target!</span>' : ''}
      <a href="${v.url}" target="_blank" class="version-link">→</a>
    </div>`
    })
    .join('')

  return `
    <div class="movie-card watchlist-card" data-tmdb-id="${tmdb.tmdb_id}">
      <button class="remove-from-watchlist" onclick="removeFromWatchlist(${tmdb.tmdb_id})" title="Remove from watchlist">×</button>
      ${posterHtml}
      <div class="movie-info">
        <div class="movie-title">${tmdb.title}${tmdb.release_year ? ' (' + tmdb.release_year + ')' : ''}</div>
        <div style="color: #666; font-size: 0.9em; margin: 5px 0;">
          Target: €${targetPrice.toFixed(2)}
        </div>
        <div class="watchlist-versions">
          ${versionsHtml || '<p style="color:#999;font-size:0.85em;">No versions found</p>'}
        </div>
      </div>
    </div>
  `
}

async function searchMovies() {
  const query = document.getElementById('search-input').value
  const maxPrice = document.getElementById('max-price-input').value
  const category = document.getElementById('category-select').value

  // Require either a query or filters
  const hasFilters = maxPrice || (category && category !== 'all')
  if (!query && !hasFilters) return

  // Build query parameters
  const params = new URLSearchParams({ q: query || '' })
  if (maxPrice) {
    params.append('max_price', maxPrice)
  }
  if (category && category !== 'all') {
    params.append('category', category)
  }

  const response = await fetch(`/api/search?${params}`)
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
    priceChange < 0 ? 'price-up' : priceChange > 0 ? 'price-down' : ''
  const priceSymbol = priceChange < 0 ? '↑' : priceChange > 0 ? '↓' : ''
  const isBoxSet = movie.is_box_set || false

  // Create poster image HTML
  let posterHtml = ''
  // Box sets always use CDON image (no TMDB)
  if (isBoxSet && movie.image_url) {
    posterHtml = `<div class="movie-poster">
            <img src="${movie.image_url}" alt="${movie.title} poster"
                 onerror="this.style.display='none'; this.parentElement.classList.add('no-poster');">
        </div>`
  } else if (movie.image_url && movie.tmdb_id) {
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

  // Badge: Box Set or TMDB
  const badgeHtml = isBoxSet
    ? '<span class="box-set-badge" title="Box Set">BOX SET</span>'
    : movie.tmdb_id
      ? '<span class="tmdb-badge" title="Matched with TMDB">TMDB</span>'
      : ''

  return `
        <div class="movie-card" id="movie-card-${movie.id}" data-product-id="${
          movie.product_id
        }" data-is-box-set="${isBoxSet}">
            ${
              showTarget
                ? `<button class="remove-from-watchlist" onclick="removeFromWatchlist('${movie.product_id}')" title="Remove from watchlist">×</button>`
                : ''
            }
            ${posterHtml}
            <div class="movie-info">
                <div class="movie-title">${movie.title}${movie.production_year ? ' (' + movie.production_year + ')' : ''}</div>
                <span class="movie-format">${movie.format}</span>
                ${badgeHtml}
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
                  showIgnore && !isBoxSet
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
    const result = await response.json()
    if (result.status === 'confirmed') {
      showNotification(result.message || 'Added to watchlist!')
      // Refresh appropriate watchlist based on type
      if (result.is_box_set) {
        loadBoxSetWatchlist()
        loadBoxSets()
      } else {
        loadWatchlist()
      }
      loadStats()
    } else if (result.status === 'queued') {
      showNotification(
        result.message || 'Added to matching queue - visit /match to confirm',
        'warning'
      )
      loadMatchQueueBadge()
    } else {
      showNotification(result.message || 'Unknown status', 'warning')
    }
  } else {
    const errorData = await response.json()
    showNotification(
      `Failed to add to watchlist: ${errorData.detail || 'Unknown error'}`,
      'error'
    )
  }
}

async function removeFromWatchlist(tmdbId) {
  if (!confirm('Remove this movie from your watchlist?')) {
    return
  }

  const response = await fetch(`/api/watchlist/${tmdbId}`, {
    method: 'DELETE',
  })

  if (response.ok) {
    // Remove the movie card from the watchlist view by finding it using tmdb_id
    const movieCard = document.querySelector(`[data-tmdb-id="${tmdbId}"]`)
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
      'Are you sure you want to ignore this movie? All versions will be removed from cheapest views.'
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
    const result = await response.json()
    if (result.status === 'confirmed') {
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

      showNotification(
        result.message || 'Movie ignored and removed from cheapest views'
      )
      // Reload cheapest lists to remove all versions of this movie
      loadCheapestBlurays()
      loadCheapest4KBlurays()
    } else if (result.status === 'queued') {
      showNotification(
        result.message || 'Added to matching queue - visit /match to confirm',
        'warning'
      )
      loadMatchQueueBadge()
    } else {
      showNotification(result.message || 'Unknown status', 'warning')
    }
  } else {
    const errorData = await response.json()
    showNotification(
      `Failed to ignore movie: ${errorData.detail || 'Unknown error'}`,
      'error'
    )
  }
}

// ==================== Box Sets ====================

async function loadBoxSets() {
  const response = await fetch('/api/box-sets')
  const boxSets = await response.json()
  const container = document.getElementById('box-sets-container')

  if (boxSets.length === 0) {
    container.innerHTML = '<p style="color: #666;">No box sets found</p>'
    return
  }

  container.innerHTML = boxSets
    .map((movie) => createMovieCard(movie, false, false))
    .join('')
}

async function loadBoxSetWatchlist() {
  const response = await fetch('/api/box-sets/watchlist')
  const watchlist = await response.json()
  const container = document.getElementById('box-set-watchlist-container')

  if (watchlist.length === 0) {
    container.innerHTML =
      '<p style="color: #666;">Box set watchlist is empty</p>'
    return
  }

  container.innerHTML = watchlist
    .map((item) => createBoxSetWatchlistCard(item))
    .join('')
}

function createBoxSetWatchlistCard(item) {
  const movie = item.movie
  const targetPrice = item.target_price

  // Create poster HTML using CDON image (no TMDB for box sets)
  let posterHtml = ''
  if (movie.image_url) {
    posterHtml = `<div class="movie-poster">
      <img src="${movie.image_url}" alt="${movie.title} poster"
           onerror="this.style.display='none'; this.parentElement.classList.add('no-poster');">
    </div>`
  } else {
    posterHtml = `<div class="movie-poster no-poster">
      <div class="poster-placeholder">📦</div>
    </div>`
  }

  const atTarget = movie.current_price && movie.current_price <= targetPrice

  return `
    <div class="movie-card watchlist-card box-set-watchlist-card" data-movie-id="${movie.id}">
      <button class="remove-from-watchlist" onclick="removeBoxSetFromWatchlist(${movie.id})" title="Remove from watchlist">×</button>
      ${posterHtml}
      <div class="movie-info">
        <div class="movie-title">${movie.title}</div>
        <span class="movie-format">${movie.format || 'Unknown'}</span>
        <span class="box-set-badge" title="Box Set">BOX SET</span>
        <div class="price-info">
          <span class="current-price">€${movie.current_price ? movie.current_price.toFixed(2) : '-'}</span>
          ${atTarget ? '<span class="target-reached">✓ Target!</span>' : ''}
        </div>
        <div style="color: #666; font-size: 0.9em; margin: 5px 0;">
          Target: €${targetPrice.toFixed(2)}
        </div>
        ${
          movie.lowest_price
            ? `
          <div class="price-history">
            Lowest: €${movie.lowest_price.toFixed(2)} | Highest: €${movie.highest_price.toFixed(2)}
          </div>
        `
            : ''
        }
        <a href="${movie.url}" target="_blank" class="movie-link">View on CDON →</a>
      </div>
    </div>
  `
}

async function removeBoxSetFromWatchlist(movieId) {
  if (!confirm('Remove this box set from your watchlist?')) {
    return
  }

  const response = await fetch(`/api/box-sets/watchlist/${movieId}`, {
    method: 'DELETE',
  })

  if (response.ok) {
    showNotification('Removed from watchlist')
    loadBoxSetWatchlist()
    loadBoxSets()
    loadStats()
  } else {
    const errorData = await response.json()
    showNotification(
      `Failed to remove from watchlist: ${errorData.detail || 'Unknown error'}`,
      'error'
    )
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
