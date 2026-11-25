// Printing script for the compact (three-column) checklists and reports
// written by ChecklistHtmlOutput and HtmlOutput.
//
// Safari (WebKit) ignores CSS columns when printing, and prints the compact
// list as one long column. Flexbox does print, so in Safari this
// rebuilds the list as "bands": each band holds about BAND_HEIGHT pixels of
// each column, laid out as three flexbox columns. A band never splits across
// pages, since that would scramble the reading order.
function scythebillMakeBands() {
  var BAND_HEIGHT = 300;
  var main = document.querySelector('.main');
  if (!main) {
    return;
  }

  // Measure each entry at the width of one band column.
  var probe = document.createElement('div');
  probe.className = 'band';
  probe.style.visibility = 'hidden';
  var probeColumns = [];
  for (var c = 0; c < 3; c++) {
    var probeColumn = document.createElement('div');
    probeColumn.className = 'col';
    probe.appendChild(probeColumn);
    probeColumns.push(probeColumn);
  }
  main.parentNode.insertBefore(probe, main);
  var items = Array.prototype.slice.call(main.children);
  var heights = items.map(function(item) {
    var copy = item.cloneNode(true);
    probeColumns[0].appendChild(copy);
    var style = window.getComputedStyle(copy);
    var height = copy.getBoundingClientRect().height
        + parseFloat(style.marginTop) + parseFloat(style.marginBottom);
    probeColumns[0].removeChild(copy);
    return height;
  });
  probe.parentNode.removeChild(probe);

  function isHeading(item) {
    return item.tagName === 'H2';
  }

  // Split into bands, never ending a band on a family heading.
  var bands = [];
  var current = [];
  var total = 0;
  items.forEach(function(item, i) {
    if (total + heights[i] > 3 * BAND_HEIGHT && current.length > 0
        && !isHeading(current[current.length - 1].item)) {
      bands.push(current);
      current = [];
      total = 0;
    }
    current.push({item: item, height: heights[i]});
    total += heights[i];
  });
  if (current.length > 0) {
    bands.push(current);
  }

  // Split each band into three columns of about equal height, again never
  // ending a column on a family heading.
  main.innerHTML = '';
  main.className = 'banded';
  bands.forEach(function(band) {
    var bandTotal = band.reduce(function(sum, entry) { return sum + entry.height; }, 0);
    var target = bandTotal / 3;
    var bandElement = document.createElement('div');
    bandElement.className = 'band';
    var column = null;
    var columnHeight = 0;
    var columnsMade = 0;
    band.forEach(function(entry, i) {
      var previousIsHeading = i > 0 && isHeading(band[i - 1].item);
      if (column === null
          || (columnsMade < 3 && columnHeight + entry.height / 2 > target && !previousIsHeading)) {
        column = document.createElement('div');
        column.className = 'col';
        bandElement.appendChild(column);
        columnsMade++;
        columnHeight = 0;
      }
      column.appendChild(entry.item);
      columnHeight += entry.height;
    });
    main.appendChild(bandElement);
  });
}

function scythebillIsSafari() {
  return !!(navigator.vendor && navigator.vendor.indexOf('Apple') > -1
      && navigator.userAgent && !navigator.userAgent.match('CriOS'));
}
