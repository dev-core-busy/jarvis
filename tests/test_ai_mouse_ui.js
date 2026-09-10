/**
 * Die Kachel „Meine Fragen" unter /ai-mouse.
 *
 * Anlass (2026-09-09): gemeldet als „in der user Kachel können weiterhin keine
 * Prompts eingetragen werden, die dann in der Anwendung erscheinen". Gemessen
 * war die Kachel in Ordnung – der Fehler lag im CLIENT, der die Fragen nach der
 * Anmeldung nie holte (dafür Abschnitt 8d in tests/test_ai_mouse.py). Dieser
 * Wächter hält die Kachel-Hälfte fest, damit die Frage beim nächsten Mal in
 * einem Zug beantwortbar ist.
 *
 * ⚠ Der ECHTE Renderer läuft gegen die ECHTE ai_mouse.html – ob eine Liste
 * ENTSTEHT und ob ein Klick wirklich sendet, kann eine Quelltext-Suche nicht
 * beantworten.
 *
 *   node tests/test_ai_mouse_ui.js      (JSDOM_PATH setzt den jsdom-Ort)
 */
const fs=require('fs');
let JSDOM=null;
for (const o of [process.env.JSDOM_PATH, 'jsdom',
                 '/tmp/node_modules/jsdom', './node_modules/jsdom',
                 process.env.HOME+'/node_modules/jsdom',
                 '/opt/jarvis/data/node_modules/jsdom', '/usr/share/nodejs/jsdom']) {
  if (!o) { continue; }
  try { JSDOM = require(o).JSDOM; break; } catch (e) { /* naechster Ort */ }
}
if (!JSDOM) {
  // Exit 2: "konnte nicht laufen" darf nie wie "bestanden" aussehen.
  console.error('jsdom nicht gefunden - Exit 2 (nicht gelaufen, nicht bestanden)');
  process.exit(2);
}
let ok=0,fail=0;const c=(t,b)=>{b?(ok++,console.log('  OK   '+t)):(fail++,console.log('  FAIL '+t))};
const wd=setTimeout(()=>{console.log('\nWACHHUND: haengt\n'+ok+' OK, '+(fail+1)+' FAIL');process.exit(1)},25000);
const d=new JSDOM(fs.readFileSync('frontend/ai_mouse.html','utf8'),{url:'https://x/ai-mouse',runScripts:'outside-only'});
const w=d.window;w.localStorage.setItem('jarvis_token','t');
const rufe=[];
w.fetch=(u,o)=>{const p=String(u).split('?')[0];rufe.push({u:p,m:(o&&o.method)||'GET',b:o&&o.body});
 const J=x=>Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(x)});
 if(p==='/api/ai-mouse/fragen'){
   if((o&&o.method)==='POST')return J({ok:true,frage:{id:'n1',titel:'Neu',prompt:'P',gemeinsam:false,darf_aendern:true}});
   if((o&&o.method)==='DELETE')return J({ok:true});
   return J({fragen:[{id:'g1',titel:'Gemeinsam',prompt:'A',gemeinsam:true,darf_aendern:false},
                     {id:'e1',titel:'Meine',prompt:'B',gemeinsam:false,darf_aendern:true}],ist_admin:false});}
 if(p==='/api/ai-mouse/health')return J({paket_bereit:true,bereiche:[],version:'1'});
 if(p==='/api/me')return J({username:'u',permissions:{ai_mouse:true}});
 return J({});};
for(const f of ['frontend/js/i18n.js','frontend/js/icons.js','frontend/js/ai_mouse.js'])
  {try{w.eval(fs.readFileSync(f,'utf8'))}catch(e){console.log('LADEFEHLER '+f+': '+e.message)}}
setTimeout(()=>{
  const $=x=>w.document.getElementById(x);
  const liste=$('am-fragen');
  c('die Fragenliste existiert',!!liste);
  const txt=liste?liste.textContent:'';
  c('die gemeinsame Frage steht da',txt.includes('Gemeinsam'));
  c('die eigene Frage steht da',txt.includes('Meine'));
  const del=liste?liste.querySelectorAll('[data-act="del"]').length:0;
  c('nur die EIGENE hat einen Loeschknopf ('+del+')',del===1);
  // ⚠ VIER AUFKLAPPBARE CONTAINER (Vorgabe 2026-09-09) – und GENAU vier:
  // „Grenzen" und „Einrichten" sind keine eigenen Karten mehr, sondern ans
  // Ende von „Was AI Mouse macht" bzw. „Anwendung holen" gewandert.
  const karten=[...w.document.querySelectorAll('.ja-card[data-klapp]')];
  c('es sind vier Klapp-Container ('+karten.length+')',karten.length===4);
  c('und zwar die richtigen',
    karten.map(k=>k.getAttribute('data-klapp')).join(',')==='was,holen,fragen,bereiche');
  c('jeder hat eine klickbare Kopfzeile',
    karten.every(k=>{const h=k.querySelector('.ja-card-head');
      return !!h&&h.getAttribute('role')==='button'&&h.getAttribute('tabindex')==='0';}));
  c('und einen eigenen Koerper',karten.every(k=>!!k.querySelector('.ja-card-body')));
  c('"Grenzen" steht IM Container "Was AI Mouse macht"',
    !!w.document.querySelector('.ja-card[data-klapp="was"] [data-i18n="aimouse.limit_h"]'));
  c('"Einrichten" steht IM Container "Anwendung holen"',
    !!w.document.querySelector('.ja-card[data-klapp="holen"] [data-i18n="aimouse.install_h"]'));
  c('beide als h3, nicht als zweite h2',
    ['limit_h','install_h'].every(k=>{
      const e=w.document.querySelector('[data-i18n="aimouse.'+k+'"]');
      return !!e&&e.tagName==='H3';}));
  c('sie stehen am ENDE ihres Containers',
    ['was','holen'].every(id=>{
      const k=w.document.querySelector('.ja-card[data-klapp="'+id+'"] .ja-card-body');
      const h3=k.querySelector('h3');
      // Nach dem h3 kommt nur noch sein eigener Inhalt, kein weiterer Absatz
      // des urspruenglichen Abschnitts.
      return !!h3&&!k.querySelector('h3 ~ p[data-i18n$="_p"]');}));

  // Auf- und Zuklappen wirkt und wird GEMERKT.
  const kw=w.document.querySelector('.ja-card[data-klapp="was"]');
  const kopfw=kw.querySelector('.ja-card-head');
  c('anfangs offen',!kw.classList.contains('is-zu'));
  kopfw.dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
  c('nach dem Klick zu',kw.classList.contains('is-zu'));
  c('aria-expanded folgt',kopfw.getAttribute('aria-expanded')==='false');
  c('der Zustand wird gemerkt',
    (w.localStorage.getItem('jarvis_aimouse_zu')||'').indexOf('was')>=0);
  kopfw.dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
  c('zweiter Klick oeffnet wieder',!kw.classList.contains('is-zu'));
  c('und raeumt den Speicher',
    (w.localStorage.getItem('jarvis_aimouse_zu')||'').indexOf('was')<0);
  // Ein Knopf in der Kopfzeile darf NICHT zuklappen (heute steht dort keiner,
  // aber die Ausnahme ist die Zusage fuer den naechsten).
  const probe=w.document.createElement('button');
  kopfw.appendChild(probe);
  probe.dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
  c('ein Knopf in der Kopfzeile klappt NICHT zu',!kw.classList.contains('is-zu'));
  probe.remove();
  // Tastatur: das Element ist ein role="button".
  kopfw.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
  c('Enter schaltet um',kw.classList.contains('is-zu'));
  kopfw.dispatchEvent(new w.KeyboardEvent('keydown',{key:' ',bubbles:true}));
  c('Leertaste ebenso',!kw.classList.contains('is-zu'));

  // ⚠ DER BLOCK „ZUSTAND" IST ENTFALLEN (Vorgabe 2026-09-09) – samt seinem
  // Renderer, seinen i18n-Schluesseln und seinem CSS. Was BLEIBEN musste: die
  // Sperre des Download-Knopfes, sonst fuehrt er zuverlaessig in eine
  // Fehlermeldung.
  c('der Zustands-Block ist weg',!$('am-status')&&!$('am-status-card'));
  const dlk=$('am-download');
  c('der Download-Knopf ist da',!!dlk);
  // Bauform des Jira-Zugangs statt .btn-primary (das hat width:100%).
  c('er traegt die Jira-Knopfklassen',
    !!dlk&&dlk.classList.contains('ja-btn')&&dlk.classList.contains('ja-btn-haupt'));
  c('und steht in einer .ja-dl-Zeile',!!dlk&&!!dlk.closest('.ja-dl'));
  c('type=button (kein Formular-Absenden)',!!dlk&&dlk.getAttribute('type')==='button');
  c('bei bereitem Paket ist er bedienbar',!!dlk&&!dlk.disabled);

  // Die Zeilen sind jetzt KARTEN (Bauform der E-Mail-Regeln).
  c('jede Frage ist eine Karte',liste&&liste.querySelectorAll('.am-q-card').length===2);
  c('die gemeinsame traegt eine Marke',liste&&liste.querySelectorAll('.am-q-badge').length===1);
  const neuB=$('am-frage-neu'),form=$('am-frage-form');
  c('der Knopf "Neue Frage" ist da',!!neuB);
  c('das Formular ist zunaechst ZU',!!form&&form.hidden);
  if(neuB)neuB.dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
  c('nach dem Klick ist es offen',!!form&&!form.hidden);
  // "Neue Frage" haengt es NICHT in eine Karte - es gehoert unter die Liste.
  c('beim Anlegen bleibt es am Heimatplatz',!!form&&!form.closest('.am-q-card'));
  const tI=$('am-f-titel'),pI=$('am-f-prompt'),sB=$('am-f-save');
  c('Eingabefelder und Speichern-Knopf vorhanden',!!tI&&!!pI&&!!sB);

  // ⚠ REGEL, KEINE LISTE (Anlass 2026-09-10, gemeldet fuer „Neue Frage"):
  // /ai-mouse laedt NUR theme.css und jira_addon.css. Ein Knopf mit
  // `.btn-primary`/`.btn-secondary` – die stehen in style.css – ist hier kein
  // halb gestylter, sondern ein NACKTER Browser-Standardknopf. Geprueft wird
  // die EIGENSCHAFT: jeder Knopf traegt mindestens eine Klasse, die das CSS
  // DIESER Seite wirklich definiert. Damit faellt auch der naechste Knopf auf,
  // ohne dass jemand eine Liste pflegt. Das Formular ist hier offen, Speichern
  // und Abbrechen sind also mit erfasst.
  //
  // Gezaehlt wird nur das ERSTE Element eines Selektors: theme.css enthaelt
  // `.jv-pc-foot .btn-primary` – wer die Klasse dort mitzaehlt, baut sich einen
  // zahnlosen Waechter, denn dieser Kontext gibt es auf /ai-mouse nicht.
  const cssTxt=['frontend/css/theme.css','frontend/css/jira_addon.css']
    .map(p=>fs.readFileSync(p,'utf8')).join('\n')
    .replace(/\/\*[\s\S]*?\*\//g,'');           // Kommentare raus (Register)
  const bekannt=new Set();
  let mSel;const reSel=/([^{}]+)\{/g;
  while((mSel=reSel.exec(cssTxt))!==null){
    mSel[1].split(',').forEach(s=>{
      const erst=s.trim().split(/[\s>+~]+/)[0];
      let mK;const reK=/\.([A-Za-z][\w-]*)/g;
      while((mK=reK.exec(erst))!==null){bekannt.add(mK[1]);}
    });
  }
  // Positivkontrolle: ohne sie waere jede Aussage unten trivial wahr.
  c('Positivkontrolle: das CSS wurde gelesen ('+bekannt.size+' Klassen)',
    bekannt.has('ja-btn')&&bekannt.size>50);
  c('Gegenprobe des Sammlers: .btn-primary gilt NICHT als definiert',
    !bekannt.has('btn-primary')&&!bekannt.has('btn-secondary'));
  const knoepfe=[...w.document.querySelectorAll('button')];
  c('es gibt ueberhaupt Knoepfe zu pruefen ('+knoepfe.length+')',knoepfe.length>=8);
  const nackt=knoepfe.filter(b=>![...b.classList].some(k=>bekannt.has(k)));
  c('jeder Knopf traegt eine Klasse, die DIESE Seite kennt'
    +(nackt.length?' – nackt: '+nackt.map(b=>b.id||'"'+b.textContent.trim().slice(0,18)+'"').join(', '):''),
    nackt.length===0);
  const neuB2=$('am-frage-neu');
  c('"Neue Frage" traegt die Knopfklasse dieser Seite',
    !!neuB2&&neuB2.classList.contains('ja-btn'));
  c('und steht in einer .ja-dl-Zeile (die .ja-actions hatte KEIN CSS)',
    !!neuB2&&!!neuB2.closest('.ja-dl'));
  c('"Speichern" ist die Hauptaktion des Formulars',
    !!sB&&sB.classList.contains('ja-btn')&&sB.classList.contains('ja-btn-haupt'));
  c('"Abbrechen" ist es NICHT',
    !!$('am-f-cancel')&&$('am-f-cancel').classList.contains('ja-btn')
    &&!$('am-f-cancel').classList.contains('ja-btn-haupt'));
  if(!(tI&&pI&&sB)){console.log('\n'+ok+' OK, '+(fail)+' FAIL');clearTimeout(wd);w.close();process.exit(1);}
  tI.value='Neu';pI.value='P';
  sB.dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
  setTimeout(()=>{
    const post=rufe.filter(r=>r.m==='POST'&&r.u==='/api/ai-mouse/fragen');
    c('der Klick sendet EINEN POST ('+post.length+')',post.length===1);
    if(post[0]){const b=JSON.parse(post[0].b);
      c('Titel und Prompt gehen mit',b.titel==='Neu'&&b.prompt==='P');}
    c('das Formular ist danach wieder zu',!!form&&form.hidden);
    // ⚠ DER KERN DER VORGABE: Bearbeiten oeffnet UNTER dem Eintrag.
    const eKarte=liste.querySelector('.am-q-card[data-qid="e1"]');
    const eBtn=eKarte&&eKarte.querySelector('[data-act="edit"]');
    c('die eigene Karte hat einen Bearbeiten-Knopf',!!eBtn);
    if(eBtn)eBtn.dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
    const f2=$('am-frage-form');
    c('das Formular sitzt IN der Karte des Eintrags',!!f2&&f2.closest('.am-q-card')===eKarte);
    c('und ist offen',!!f2&&!f2.hidden);
    c('mit den Werten dieses Eintrags',
      ($('am-f-titel')||{}).value==='Meine'&&($('am-f-prompt')||{}).value==='B');
    // Ein ZWEITER Klick schliesst - sonst tut der Knopf sichtbar nichts.
    if(eBtn)eBtn.dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
    c('ein zweiter Klick schliesst',!!$('am-frage-form')&&$('am-frage-form').hidden);
    c('und holt es aus der Karte zurueck',
      !!$('am-frage-form')&&!$('am-frage-form').closest('.am-q-card'));
    // ⚠ DER GEFAEHRLICHE FALL: die Liste wird neu gezeichnet, WAEHREND das
    // Formular offen in einer Karte haengt. Ohne Heimholen loescht
    // `box.innerHTML = …` es mit – danach gibt es kein Formular mehr, und der
    // Bearbeiten-Knopf ist tot. Genau das haben zwei Gegenproben zuerst nicht
    // gefangen, weil der Waechter nach dem Oeffnen nie neu zeichnete.
    if(eBtn)eBtn.dispatchEvent(new w.MouseEvent('click',{bubbles:true}));  // wieder auf
    w.__amFragenZeichnen&&w.__amFragenZeichnen();
    const f3=$('am-frage-form');
    c('das Formular ueberlebt ein Neuzeichnen',!!f3);
    c('und sitzt wieder unter SEINEM Eintrag',
      !!f3&&!!f3.closest('.am-q-card')&&
      f3.closest('.am-q-card').getAttribute('data-qid')==='e1');
    c('mit unveraenderten Werten',($('am-f-titel')||{}).value==='Meine');
    // Zurueck in den geschlossenen Zustand fuer die folgenden Pruefungen.
    const eBtn2=w.document.querySelector('.am-q-card[data-qid="e1"] [data-act="edit"]');
    if(eBtn2)eBtn2.dispatchEvent(new w.MouseEvent('click',{bubbles:true}));

    // Die gemeinsame Frage darf ein Nicht-Admin nicht anfassen.
    const gKarte=liste.querySelector('.am-q-card[data-qid="g1"]');
    c('die gemeinsame Karte hat KEINE Knoepfe',
      !!gKarte&&gKarte.querySelectorAll('.am-q-btn').length===0);
    c('die Liste wird danach neu geholt',
      rufe.filter(r=>r.m==='GET'&&r.u==='/api/ai-mouse/fragen').length>=2);
    // Loeschen: es darf NUR nach Rueckfrage passieren und nur die eigene Frage.
    w.confirm=()=>true;
    const dB=liste.querySelector('[data-act="del"]');
    if(dB)dB.dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
    setTimeout(()=>{
      const del=rufe.filter(r=>r.m==='DELETE');
      c('Loeschen sendet EIN DELETE ('+del.length+')',del.length===1);
      c('und zwar auf die EIGENE Frage',!!del[0]&&del[0].u.endsWith('/e1'));
      let ohne=0;w.confirm=()=>false;
      const vor=rufe.filter(r=>r.m==='DELETE').length;
      const dB2=w.document.querySelector('[data-act="del"]');
      if(dB2)dB2.dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
      setTimeout(()=>{
        c('abgelehnte Rueckfrage loescht NICHTS',
          rufe.filter(r=>r.m==='DELETE').length===vor);
          // Ohne gebautes Paket MUSS der Knopf gesperrt sein und den Grund nennen.
      w.__amHealth&&w.__amHealth({paket_bereit:false,bereiche:[],version:'1'});
      const dl2=w.document.getElementById('am-download');
      c('ohne Paket ist der Knopf gesperrt',!!dl2&&dl2.disabled===true);
      c('und nennt den Grund',!!dl2&&(dl2.title||'').length>10);
      console.log('\n'+ok+' OK, '+fail+' FAIL');clearTimeout(wd);w.close();process.exit(fail?1:0);
      },250);
    },300);
  },400);
},500);
