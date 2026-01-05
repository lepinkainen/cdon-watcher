// TMDB Matching Queue Page Logic

let currentMovieId = null
let queuePosition = 0
let totalInQueue = 0
let includeSkipped = false

window.addEventListener('load', () => {
  loadCurrentMatch()
})

async function loadCurrentMatch() {
  const contentEl = document.getElementById('match-content')
  const badgeEl = document.getElementById('queue-badge')

  try {
    const params = new URLSearchParams({
      offset: queuePosition,
      include_skipped: includeSkipped,
    })
    const response = await fetch(`/api/match/queue?${params}`)
    const data = await response.json()

    totalInQueue = data.total
    badgeEl.textContent = `${totalInQueue} pending`

    if (!data.movie) {
      // Empty queue
      contentEl.innerHTML = `
        <div class="empty-queue">
          <h2>All caught up!</h2>
          <p>No movies waiting for TMDB matching.</p>
          ${
            !includeSkipped && totalInQueue === 0
              ? ''
              : `<button class="btn-nav" onclick="toggleSkipped()">
              ${includeSkipped ? 'Hide Skipped' : 'Show Skipped Items'}
            </button>`
          }
        </div>
      `
      return
    }

    currentMovieId = data.movie.id
    renderMatchUI(data)
  } catch (error) {
    console.error('Failed to load match queue:', error)
    contentEl.innerHTML = `
      <div class="empty-queue">
        <h2>Error loading queue</h2>
        <p>${error.message}</p>
      </div>
    `
  }
}

function renderMatchUI(data) {
  const contentEl = document.getElementById('match-content')
  const movie = data.movie
  const candidates = data.candidates || []

  // Create poster HTML for source movie
  let sourcePosterHtml = ''
  if (movie.image_url) {
    sourcePosterHtml = `<img src="${movie.image_url}" alt="${movie.title}" class="source-movie-poster" onerror="this.style.display='none'">`
  } else {
    sourcePosterHtml = `<div class="source-movie-poster" style="display:flex;align-items:center;justify-content:center;font-size:2em;">🎬</div>`
  }

  // Create candidates HTML
  const candidatesHtml = candidates
    .map((candidate) => {
      const confidenceClass = getConfidenceClass(candidate.confidence_score)
      const confidencePercent = Math.round(candidate.confidence_score * 100)

      let posterHtml = ''
      if (candidate.poster_url) {
        posterHtml = `<img src="${candidate.poster_url}" alt="${candidate.title}" class="candidate-poster" onerror="this.style.display='none'">`
      } else {
        posterHtml = `<div class="candidate-poster" style="display:flex;align-items:center;justify-content:center;font-size:1.5em;">🎬</div>`
      }

      return `
      <div class="candidate-card" onclick="confirmMatch(${candidate.tmdb_id})">
        ${posterHtml}
        <div class="candidate-info">
          <h4>
            ${candidate.title} ${candidate.release_year ? `(${candidate.release_year})` : ''}
            <span class="confidence-badge ${confidenceClass}">${confidencePercent}% match</span>
          </h4>
          <div class="candidate-meta">
            ${candidate.director ? `<span>Director: ${candidate.director}</span>` : ''}
            ${candidate.cast && candidate.cast.length > 0 ? `<span>Cast: ${candidate.cast.slice(0, 3).join(', ')}</span>` : ''}
          </div>
          ${candidate.overview ? `<div class="candidate-overview">${candidate.overview}</div>` : ''}
        </div>
      </div>
    `
    })
    .join('')

  contentEl.innerHTML = `
    <div class="source-movie">
      <h3>Source Movie (from CDON)</h3>
      <div class="source-movie-info">
        ${sourcePosterHtml}
        <div class="source-movie-details">
          <h4>${movie.title}</h4>
          <div class="source-movie-meta">
            ${movie.production_year ? `<span>Year: ${movie.production_year}</span>` : ''}
            <span>Format: ${movie.format}</span>
            ${movie.current_price ? `<span>Price: €${movie.current_price.toFixed(2)}</span>` : ''}
          </div>
          ${movie.url ? `<a href="${movie.url}" target="_blank" class="movie-link" style="margin-top:10px;display:inline-block;">View on CDON →</a>` : ''}
        </div>
      </div>
    </div>

    <div class="candidates-section">
      <h3>Select TMDB Match:</h3>
      ${candidates.length > 0 ? candidatesHtml : '<p style="color:#666;">No TMDB candidates found for this movie.</p>'}
    </div>

    <div class="match-actions">
      <button class="btn-no-match" onclick="markNoMatch()">No Match Found</button>
      <button class="btn-skip" onclick="skipMovie()">Skip for Now</button>
      <div class="nav-spacer"></div>
      <button class="btn-nav" onclick="navigateQueue(-1)" ${queuePosition === 0 ? 'disabled' : ''}>← Prev</button>
      <button class="btn-nav" onclick="navigateQueue(1)" ${queuePosition >= totalInQueue - 1 ? 'disabled' : ''}>Next →</button>
    </div>
  `
}

function getConfidenceClass(score) {
  if (score >= 0.8) return 'confidence-high'
  if (score >= 0.5) return 'confidence-medium'
  return 'confidence-low'
}

async function confirmMatch(tmdbId) {
  if (!currentMovieId) return

  try {
    const response = await fetch('/api/match/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        movie_id: currentMovieId,
        tmdb_id: tmdbId,
      }),
    })

    if (response.ok) {
      showNotification('Match confirmed!')
      // Move to next item (stay at same position since item was removed)
      loadCurrentMatch()
    } else {
      const error = await response.json()
      showNotification(
        `Failed to confirm match: ${error.detail || 'Unknown error'}`,
        'error'
      )
    }
  } catch (error) {
    console.error('Failed to confirm match:', error)
    showNotification('Failed to confirm match', 'error')
  }
}

async function markNoMatch() {
  if (!currentMovieId) return

  if (
    !confirm(
      'Mark this movie as having no TMDB match? It will be excluded from TMDB-based features.'
    )
  ) {
    return
  }

  try {
    const response = await fetch('/api/match/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        movie_id: currentMovieId,
        tmdb_id: null,
      }),
    })

    if (response.ok) {
      showNotification('Marked as no match')
      loadCurrentMatch()
    } else {
      const error = await response.json()
      showNotification(
        `Failed to mark as no match: ${error.detail || 'Unknown error'}`,
        'error'
      )
    }
  } catch (error) {
    console.error('Failed to mark no match:', error)
    showNotification('Failed to mark as no match', 'error')
  }
}

async function skipMovie() {
  if (!currentMovieId) return

  try {
    const response = await fetch('/api/match/skip', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        movie_id: currentMovieId,
      }),
    })

    if (response.ok) {
      showNotification('Skipped for now')
      loadCurrentMatch()
    } else {
      const error = await response.json()
      showNotification(
        `Failed to skip: ${error.detail || 'Unknown error'}`,
        'error'
      )
    }
  } catch (error) {
    console.error('Failed to skip:', error)
    showNotification('Failed to skip', 'error')
  }
}

function navigateQueue(direction) {
  const newPosition = queuePosition + direction
  if (newPosition >= 0 && newPosition < totalInQueue) {
    queuePosition = newPosition
    loadCurrentMatch()
  }
}

function toggleSkipped() {
  includeSkipped = !includeSkipped
  queuePosition = 0
  loadCurrentMatch()
}

// Notification system (same as main.js)
function showNotification(message, type = 'success', duration = 4000) {
  let container = document.querySelector('.notification-container')
  if (!container) {
    container = document.createElement('div')
    container.className = 'notification-container'
    document.body.appendChild(container)
  }

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

  setTimeout(() => notification.classList.add('show'), 10)
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
