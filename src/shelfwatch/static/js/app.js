// Row actions (wish / ignore / unignore) and manual matching without reloads.
;(function () {
  function post(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then(function (r) {
      if (!r.ok) throw new Error(r.status + ' ' + r.statusText)
      return r.json()
    })
  }

  function container(el) {
    return el.closest('[data-product-id]')
  }

  function fade(node) {
    if (!node) return
    node.classList.add('gone')
    setTimeout(function () {
      node.remove()
      applyQueueFilter()
    }, 300)
  }

  document.addEventListener('click', function (event) {
    var button = event.target.closest('[data-action], [data-match]')
    if (!button) return
    var node = container(button)
    if (!node) return
    var id = node.getAttribute('data-product-id')

    if (button.hasAttribute('data-action')) {
      var action = button.getAttribute('data-action')
      event.preventDefault()
      button.disabled = true
      post('/api/v2/products/' + id + '/' + action)
        .then(function () {
          if (action === 'wish') {
            var tag = document.createElement('span')
            tag.className = 'tag wish'
            tag.textContent = 'on wishlist'
            var title = node.querySelector('td.title')
            if (title) title.appendChild(tag)
            button.remove()
            return
          }
          fade(node)
        })
        .catch(function (error) {
          button.disabled = false
          alert('Action failed: ' + error.message)
        })
      return
    }

    var value = button.getAttribute('data-match')
    event.preventDefault()
    post('/api/v2/products/' + id + '/match', {
      tmdb_id: value === 'none' ? null : parseInt(value, 10),
    })
      .then(function () {
        fade(node)
      })
      .catch(function (error) {
        alert('Match failed: ' + error.message)
      })
  })

  document.addEventListener('submit', function (event) {
    var form = event.target
    if (!form.hasAttribute('data-search')) return
    event.preventDefault()
    var node = container(form)
    var results = node.querySelector('ul.results')
    var q = form.q.value.trim()
    var year = form.year.value.trim()
    var url =
      '/api/v2/tmdb/search?q=' +
      encodeURIComponent(q) +
      (year ? '&year=' + encodeURIComponent(year) : '')
    results.innerHTML = '<li>Searching…</li>'
    fetch(url)
      .then(function (r) {
        if (!r.ok) throw new Error(r.status + ' ' + r.statusText)
        return r.json()
      })
      .then(function (items) {
        results.innerHTML = ''
        if (!items.length) {
          results.innerHTML = '<li>No results</li>'
          return
        }
        items.forEach(function (c) {
          var li = document.createElement('li')
          var b = document.createElement('button')
          b.setAttribute('data-match', c.tmdb_id)
          b.textContent = 'Use'
          li.appendChild(b)
          li.appendChild(
            document.createTextNode(
              ' ' +
                c.title +
                ' (' +
                (c.release_year || '?') +
                ')' +
                (c.original_title && c.original_title !== c.title
                  ? ' · ' + c.original_title
                  : '')
            )
          )
          results.appendChild(li)
        })
      })
      .catch(function (error) {
        results.innerHTML = '<li>Search failed: ' + error.message + '</li>'
      })
  })

  var queueFilter = document.getElementById('queue-filter')
  var queueCount = document.getElementById('queue-count')
  var queueTabs = document.querySelectorAll('[role="tab"][data-tab]')
  var activeTab = 'ambiguous'

  // Ambiguous and unmatched items as tabs, combined with the title filter.
  function applyQueueFilter() {
    if (!queueFilter) return
    var words = queueFilter.value.toLowerCase().split(/\s+/).filter(Boolean)
    var items = document.querySelectorAll('section.queue-item')
    var inTab = 0
    var shown = 0
    var totals = {}
    items.forEach(function (item) {
      var tab = item.getAttribute('data-tab')
      totals[tab] = (totals[tab] || 0) + 1
      var text = (item.getAttribute('data-filter') || '').toLowerCase()
      var match = words.every(function (w) {
        return text.indexOf(w) !== -1
      })
      var here = tab === activeTab
      item.hidden = !(here && match)
      if (here) inTab++
      if (here && match) shown++
    })
    queueTabs.forEach(function (button) {
      var count = button.querySelector('.count')
      if (count)
        count.textContent = totals[button.getAttribute('data-tab')] || 0
    })
    if (queueCount) {
      queueCount.textContent = words.length
        ? shown + ' of ' + inTab + ' items'
        : inTab + ' items'
    }
  }

  function selectQueueTab(tab) {
    activeTab = tab
    queueTabs.forEach(function (button) {
      button.setAttribute(
        'aria-selected',
        button.getAttribute('data-tab') === tab ? 'true' : 'false'
      )
    })
    applyQueueFilter()
  }

  // A link to one item (/queue#product-123) opens the tab that holds it.
  function showLinkedItem() {
    var target = location.hash
      ? document.getElementById(location.hash.slice(1))
      : null
    var tab = target && target.getAttribute('data-tab')
    if (!tab) return
    selectQueueTab(tab)
    target.scrollIntoView()
  }

  queueTabs.forEach(function (button) {
    button.addEventListener('click', function () {
      selectQueueTab(button.getAttribute('data-tab'))
    })
  })

  if (queueFilter) {
    applyQueueFilter()
    showLinkedItem()
    window.addEventListener('hashchange', showLinkedItem)
    queueFilter.addEventListener('input', applyQueueFilter)
    queueFilter.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        queueFilter.value = ''
        applyQueueFilter()
      }
    })
  }

  var filters = document.querySelector('form.filters:not(.queue-filter)')
  if (filters) {
    filters.querySelectorAll('select').forEach(function (select) {
      select.addEventListener('change', function () {
        filters.requestSubmit ? filters.requestSubmit() : filters.submit()
      })
    })
  }
})()
