
    (function(){
      try{
        var t = localStorage.getItem('ffp-theme');
        if(t === 'dark' || t === 'light') document.documentElement.setAttribute('data-theme', t);
      }catch(e){}
    })();
  