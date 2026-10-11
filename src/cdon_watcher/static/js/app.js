// Row actions (watch / ignore / unwatch / unignore) and manual matching without reloads.
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
          if (
            action === 'ignore' ||
            action === 'unignore' ||
            action === 'unwatch'
          ) {
            if (
              node.tagName === 'TR' &&
              action === 'unwatch' &&
              !node.closest('section.watchlist')
            ) {
              button.textContent = '☆'
              button.setAttribute('data-action', 'watch')
              button.disabled = false
              return
            }
            fade(node)
            return
          }
          button.textContent = '★'
          button.setAttribute('data-action', 'unwatch')
          button.disabled = false
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

  var filters = document.querySelector('form.filters')
  if (filters) {
    filters.querySelectorAll('select').forEach(function (select) {
      select.addEventListener('change', function () {
        filters.requestSubmit ? filters.requestSubmit() : filters.submit()
      })
    })
  }
})()
