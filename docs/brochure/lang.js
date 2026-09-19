// Shared by brochure.html and company.html.
// ?lang=zh swaps every [data-zh] element's content before first paint of images.
(function () {
  var lang = new URLSearchParams(location.search).get('lang') === 'zh' ? 'zh' : 'en';
  document.documentElement.lang = lang;
  document.addEventListener('DOMContentLoaded', function () {
    if (lang === 'zh') {
      document.querySelectorAll('[data-zh]').forEach(function (el) { el.innerHTML = el.dataset.zh; });
      if (document.documentElement.dataset.zhTitle) document.title = document.documentElement.dataset.zhTitle;
    }
    // Screenshots: shots/<name>-<lang>.png, falling back to the other language, then a placeholder.
    document.querySelectorAll('[data-shot]').forEach(function (box) {
      var name = box.dataset.shot;
      var langs = lang === 'zh' ? ['zh', 'cn', 'en'] : ['en', 'zh', 'cn'];
      var stems = box.dataset.shared ? [name] : langs.map(function (l) { return name + '-' + l; });
      var tries = [];
      stems.forEach(function (st) { ['png', 'jpeg', 'jpg'].forEach(function (e) { tries.push(st + '.' + e); }); });
      var img = new Image();
      var next = function () {
        var src = tries.shift();
        if (!src) {
          box.innerHTML = '<div class="ph">' + box.dataset.label + '<br>shots/' + name +
            (box.dataset.shared ? '' : '-' + lang) + '.png</div>';
          return;
        }
        img.onerror = next;
        img.onload = function () { box.innerHTML = ''; box.appendChild(img); };
        // Chat shots are read from the copies build.py trims; back office shots as dropped in.
        img.src = (box.dataset.shared ? 'shots/' : 'shots/_cropped/') + src;
      };
      next();
    });
  });
})();
