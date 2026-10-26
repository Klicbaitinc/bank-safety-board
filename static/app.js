(function () {
  var base = document.body.getAttribute("data-base") || "";
  var kindLabel = { b: "Bank", c: "Credit union", f: "Failed bank" };

  document.querySelectorAll("table.sortable").forEach(function (table) {
    var body = table.tBodies[0];
    if (!body) return;
    table.querySelectorAll("th[data-sort]").forEach(function (th) {
      th.tabIndex = 0;
      th.setAttribute("aria-sort", "none");
      function sort() {
        var dir = th.getAttribute("aria-sort") === "ascending" ? -1 : 1;
        table.querySelectorAll("th[data-sort]").forEach(function (other) {
          other.setAttribute("aria-sort", "none");
        });
        th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
        var index = th.cellIndex;
        var numeric = th.getAttribute("data-sort") === "num";
        var rows = Array.prototype.slice.call(body.rows);
        rows.sort(function (a, b) {
          var av = a.cells[index].getAttribute("data-v") || "";
          var bv = b.cells[index].getAttribute("data-v") || "";
          var aEmpty = av === "";
          var bEmpty = bv === "";
          if (aEmpty || bEmpty) return aEmpty === bEmpty ? 0 : aEmpty ? 1 : -1;
          if (numeric) return (parseFloat(av) - parseFloat(bv)) * dir;
          return av.localeCompare(bv) * dir;
        });
        rows.forEach(function (row) { body.appendChild(row); });
      }
      th.addEventListener("click", sort);
      th.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          sort();
        }
      });
    });
  });

  var failInput = document.getElementById("fail-q");
  if (failInput) {
    var failTable = document.getElementById("failures");
    var failRows = Array.prototype.slice.call(failTable.tBodies[0].rows);
    var failCount = document.getElementById("fail-count");
    function filterFailures() {
      var query = failInput.value.trim().toLowerCase();
      var shown = 0;
      failRows.forEach(function (row) {
        var ok = !query || (row.getAttribute("data-q") || "").indexOf(query) !== -1;
        row.hidden = !ok;
        if (ok) shown += 1;
      });
      if (failCount) failCount.textContent = "Showing " + shown.toLocaleString() + " of " + failRows.length.toLocaleString();
    }
    failInput.addEventListener("input", filterFailures);
    filterFailures();
  }

  var input = document.getElementById("q");
  var results = document.getElementById("results");
  if (!input || !results) return;
  var kinds = (input.getAttribute("data-kinds") || "b c f").split(/\s+/);
  var index = null;
  var pending = null;

  function loadIndex() {
    if (index) return Promise.resolve(index);
    if (pending) return pending;
    pending = fetch(base + "/search-index.json")
      .then(function (response) { return response.json(); })
      .then(function (data) { index = data; return data; });
    return pending;
  }

  function render(items, total) {
    results.replaceChildren();
    if (!items.length) {
      var empty = document.createElement("p");
      empty.className = "muted small";
      empty.style.padding = "10px 12px";
      empty.textContent = "No matching institution.";
      results.appendChild(empty);
      results.hidden = false;
      return;
    }
    items.forEach(function (item) {
      var link = document.createElement("a");
      link.href = base + item.u;
      var kind = document.createElement("span");
      kind.className = "kind";
      kind.textContent = kindLabel[item.k] || "Institution";
      var name = document.createElement("b");
      name.textContent = item.name;
      var meta = document.createElement("span");
      var bits = [];
      if (item.where) bits.push(item.where);
      if (item.k === "f" && item.date) bits.push("failed " + item.date);
      else if (item.id) bits.push((item.k === "c" ? "charter " : "cert ") + item.id);
      meta.textContent = bits.join(" · ");
      link.appendChild(kind);
      link.appendChild(name);
      link.appendChild(meta);
      results.appendChild(link);
    });
    if (total > items.length) {
      var more = document.createElement("p");
      more.className = "muted small";
      more.style.padding = "8px 12px";
      more.textContent = "Showing " + items.length + " of " + total + ". Type more of the name.";
      results.appendChild(more);
    }
    results.hidden = false;
  }

  input.addEventListener("input", function () {
    var query = input.value.trim().toLowerCase();
    var numeric = /^\d+$/.test(query);
    if (query.length < 2 && !numeric) {
      results.hidden = true;
      results.replaceChildren();
      return;
    }
    loadIndex().then(function (rows) {
      var hits = [];
      for (var i = 0; i < rows.length; i++) {
        var item = rows[i];
        if (kinds.indexOf(item.k) === -1) continue;
        var hay = item.h || "";
        var rank = -1;
        if (numeric && String(item.id) === query) rank = 3;
        else if (hay.indexOf(query) !== -1) rank = item.name.toLowerCase().indexOf(query) === 0 ? 2 : 1;
        if (rank >= 0) hits.push({ rank: rank, item: item });
      }
      hits.sort(function (a, b) {
        if (b.rank !== a.rank) return b.rank - a.rank;
        return a.item.name.localeCompare(b.item.name);
      });
      render(hits.slice(0, 20).map(function (hit) { return hit.item; }), hits.length);
    }).catch(function () {
      results.hidden = false;
      results.textContent = "Search index could not be loaded.";
    });
  });
})();
