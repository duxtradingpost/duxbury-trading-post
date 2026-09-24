#!/usr/bin/env python3
"""Backfill Shopify tags on products that arrived from the eBay/Heystack sync untagged.

    python3 reports/tag-backfill.py            # dry run
    python3 reports/tag-backfill.py --apply    # write via tagsAdd

Why this exists
---------------
224 of 452 active+draft products had ZERO tags on 2026-09-21 - everything that
came in through the sync. They were invisible to every storefront filter
(Football, Graded, Rookie, Numbered, Parallel, Auto) and to team/player search.

Everything is derived from the product TITLE, and every vocabulary it uses is
read back out of the store's own existing tags, so it cannot invent a new tag
shape. See memory dtp-shopify-tag-conventions: prefixed families
(Team:/Player:/Brand:/Year:/League:) plus bare condition words.

The player->team map is built from products that already carry exactly ONE
Player: and ONE Team: tag, which is what lets a title naming only "Josh Allen"
still get "Team: Bills". Multi-player combo cards are excluded from map-building
(they would make every player look like they play for three teams) but are still
tagged with every player and team found in their title.

tagsAdd only ADDS - it never removes - so a re-run is safe and existing tags are
never disturbed. Tag changes must go through the Admin API, never the product
CSV importer, which replaces the whole Tags field (see
memory shopify-tag-csv-import-dead-end).
"""
import json, os, re, sys, time, urllib.request, collections, argparse

TOKEN=open(os.path.expanduser('~/.dtp-shopify-token')).read().strip()
URL='https://hmbhxb-y0.myshopify.com/admin/api/2026-07/graphql.json'

def gql(q, v=None):
    req=urllib.request.Request(URL, data=json.dumps({'query':q,'variables':v or {}}).encode(),
        headers={'Content-Type':'application/json','X-Shopify-Access-Token':TOKEN})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r: d=json.loads(r.read())
            break
        except Exception as e:
            if attempt==3: raise
            time.sleep(2*(attempt+1))
    if 'errors' in d: sys.exit('GQL ERROR: '+json.dumps(d['errors'])[:400])
    return d['data']

def fetch_products():
    Q='''query($after:String){ products(first:250, after:$after){
        pageInfo{hasNextPage endCursor}
        nodes{ id title status tags } } }'''
    out=[]; after=None
    while True:
        c=gql(Q,{'after':after})['products']; out+=c['nodes']
        if not c['pageInfo']['hasNextPage']: break
        after=c['pageInfo']['endCursor']
    return out

def all_tags():
    """EVERY product tag, paginated.

    This used to be a bare productTags(first:250). Tags come back ALPHABETICALLY,
    and once ~300 "Player: ..." tags existed they pushed every "Team: ..." tag
    past position 250 - so the team vocabulary silently became EMPTY and no
    product could be given a Team: tag again. Found 2026-09-21 when 47 cards
    whose titles plainly ended in "Chiefs", "Colts", "49ers" kept coming back
    untagged. Same failure as the storefront's un-paginated first:250: a hard
    page cap that looks like a limit and is really a truncation.
    """
    out=[]; after=None
    while True:
        d=gql('query($after:String){productTags(first:250, after:$after){'
              'pageInfo{hasNextPage endCursor} edges{node}}}', {'after':after})['productTags']
        out += [e['node'] for e in d['edges']]
        if not d['pageInfo']['hasNextPage']: break
        after=d['pageInfo']['endCursor']
    return out

norm=lambda s: re.sub(r'[^a-z0-9 ]','',s.lower()).strip()
def val(tags,p): return [t[len(p):].strip() for t in tags if t.startswith(p)]
def has(tags,p): return any(t.startswith(p) for t in tags)

BRAND_WORDS={'topps':'Topps','panini':'Panini','bowman':'Bowman','fleer':'Fleer','leaf':'Leaf',
 'skybox':'Skybox','pokemon':'Pokemon','donruss':'Panini','optic':'Panini','prizm':'Panini',
 'mosaic':'Panini','score':'Panini','select':'Panini','immaculate':'Panini','chronicles':'Panini',
 'absolute':'Panini','phoenix':'Panini','revolution':'Panini','certified':'Panini','obsidian':'Panini',
 'spectra':'Panini','illusions':'Panini','origins':'Panini','contenders':'Panini','wild':'Wild Card','sage':'SAGE','playoff':'Playoff','hit':'SAGE'}
SET_STOP={'topps','panini','bowman','upper','deck','leaf','fleer','skybox','score','donruss','optic',
 'prizm','mosaic','chrome','sapphire','series','select','immaculate','chronicles','absolute','phoenix',
 'revolution','finest','pristine','cosmic','tribute','extended','draft','university','contenders',
 'clearly','obsidian','spectra','illusions','certified','origins','gold','black',
 'wild','card','sage','hit','playoff','honors'}
NOISE={'rainbow','foil','crackle','sandglitter','diamante','leather','refractor','mojo','wave','holo',
 'aqua','pound','slays','dawg','combo','card','team','league','leaders','greats','game','finest'}
CITY={'seattle','buffalo','kansas','city','san','francisco','new','england','york','los','angeles',
 'tampa','bay','green','dallas','chicago','detroit','denver','miami','cleveland','pittsburgh','houston'}
SUFFIX={'jr','sr','ii','iii','iv'}
# Titles that came in mangled or duplicated - never invent a Player: tag from these.
BAD_TITLE=re.compile(r'\bUar Bernard\b|\bPuca\b', re.I)

def extract_new_player(title):
    head=title.split('#')[0].strip()
    w=[t.strip(',') for t in head.split()]
    if w and re.match(r'^(19|20)\d\d(-\d\d)?$',w[0]): w=w[1:]
    while w and w[0].lower().rstrip('.') in SET_STOP: w=w[1:]
    out=[]
    for t in w:
        low=t.lower().rstrip('.')
        if low in SET_STOP or low in NOISE or low in CITY: break
        if re.match(r"^[A-Z][A-Za-z'\.\-]*$",t) or low in SUFFIX: out.append(t)
        else: break
    while out and out[0].lower().rstrip('.') in SUFFIX: out.pop(0)
    core=[x for x in out if x.lower().rstrip('.') not in SUFFIX]
    return ' '.join(out) if 2<=len(core)<=3 else None

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--apply',action='store_true')
    a=ap.parse_args()
    prods=fetch_products(); tags=all_tags()
    players=[t[7:].strip() for t in tags if t.startswith('Player:')]
    teams=[t[5:].strip() for t in tags if t.startswith('Team:')]

    # maps learned from the store's OWN correctly-tagged products
    p2t={}; c=collections.defaultdict(collections.Counter)
    t2sport={}; sp=collections.defaultdict(collections.Counter)
    SPORTS={'Football','Baseball','Basketball','Hockey','Soccer','Pokemon'}
    for p in prods:
        pl,tm=val(p['tags'],'Player:'),val(p['tags'],'Team:')
        if len(pl)==1 and len(tm)==1: c[pl[0]][tm[0]]+=1
        for t in tm:
            for s in SPORTS & set(p['tags']): sp[t][s]+=1
            for lg in val(p['tags'],'League:'): sp[t]['League: '+lg]+=1
    for k,v in c.items():
        if len(v)==1: p2t[k]=v.most_common(1)[0][0]
    for k,v in sp.items(): t2sport[k]=[x for x,_ in v.most_common(3)]

    pl_s=sorted(players,key=len,reverse=True); tm_s=sorted(teams,key=len,reverse=True)
    # Target anything MISSING a Player: or Team: tag, not just zero-tag products.
    # The original version only took products with no tags at all, so anything
    # partially tagged - e.g. a card that picked up Raw/Year/Brand but never a
    # Team - was skipped on every run and could never be completed. Found
    # 2026-09-21: 47 of the 248 cards at $1.99 had no Team: tag even though the
    # team was right there in the title.
    targets=[p for p in prods
             if not p['tags'] or not has(p['tags'],'Player:') or not has(p['tags'],'Team:')]
    plan=[]
    for p in targets:
        t=p['title']; nt=norm(t); add=set()
        # --- Player / Team ---
        existing_pl=val(p['tags'],'Player:')
        # Trust a Player: tag that is already there - never second-guess it.
        found_pl=existing_pl or [x for x in pl_s if re.search(r'\b'+re.escape(norm(x))+r'\b',nt)]
        found_tm=[x for x in tm_s if re.search(r'\b'+re.escape(norm(x))+r'\b',nt)]
        if not found_pl and not re.search(r'pokemon',t,re.I) and not BAD_TITLE.search(t):
            n=extract_new_player(t)
            if n: found_pl=[n]
        for x in found_pl: add.add('Player: '+x)
        for x in found_tm: add.add('Team: '+x)
        if found_pl and not found_tm:
            for x in found_pl:
                if x in p2t: add.add('Team: '+p2t[x])
        # --- sport / league, learned from the team ---
        for x in (found_tm or [p2t[y] for y in found_pl if y in p2t]):
            for s in t2sport.get(x,[]): add.add(s)
        if re.search(r'pokemon',t,re.I): add.update({'Pokemon','Brand: Pokemon'})
        # --- year, brand ---
        m=re.match(r'^((19|20)\d\d)',t)
        if m: add.add('Year: '+m.group(1))
        for w,b in BRAND_WORDS.items():
            if re.search(r'\b'+w+r'\b',t,re.I): add.add('Brand: '+b); break
        # --- condition / attributes ---
        add.add('Graded' if re.search(r'\b(PSA|BGS|SGC|CGC)\s*\d',t,re.I) else 'Raw')
        if re.search(r'\bRC\b|\bRookie\b',t,re.I): add.add('Rookie')
        if re.search(r'\bauto(graph)?\b',t,re.I): add.add('Auto')
        if re.search(r'/\d{1,5}\b',t): add.add('Numbered')
        if re.search(r'refractor|prizm|mojo|foil|wave|holo|parallel|shimmer|diamante|sparkle|lazer|hyper|velocity|disco|sandglitter|crackle',t,re.I): add.add('Parallel')
        if re.search(r'\b(jersey|patch|relic|memorabilia|\bMEM\b)\b',t,re.I): add.add('Relic')
        if re.search(r'\b(sealed|box|blaster|hobby|mega)\b',t,re.I): add.add('Sealed')
        plan.append({'id':p['id'],'title':t,'tags':sorted(add)})

    import collections as _c
    zero=len([x for x in targets if not x['tags']])
    print(f"{len(prods)} products (all statuses); {len(targets)} needing tags "
          f"({zero} with none at all, {len(targets)-zero} missing Player:/Team:)")
    print("   by status:", dict(_c.Counter(p['status'] for p in targets)), "\n")
    dist=collections.Counter(len(x['tags']) for x in plan)
    print("tags per product:", dict(sorted(dist.items())))
    tally=collections.Counter(t for x in plan for t in x['tags'])
    print(f"\ntop tags to be added ({sum(tally.values())} total across {len(plan)} products):")
    for t,n in tally.most_common(18): print(f"   {n:4}  {t}")
    thin=[x for x in plan if len(x['tags'])<3]
    if thin:
        print(f"\n{len(thin)} products would get fewer than 3 tags:")
        for x in thin[:8]: print(f"   {x['tags']} | {x['title'][:60]}")
    if not a.apply:
        print("\n--- sample ---")
        for x in plan[:4]: print(f"  {x['title'][:66]}\n     {', '.join(x['tags'])}")
        print("\nDry run. Add --apply to write.")
        return
    M='''mutation($id:ID!,$tags:[String!]!){ tagsAdd(id:$id,tags:$tags){
        node{id} userErrors{field message} } }'''
    ok=fail=0
    for i,x in enumerate(plan,1):
        d=gql(M,{'id':x['id'],'tags':x['tags']})
        errs=d['tagsAdd']['userErrors']
        if errs: fail+=1; print(f"  FAIL {x['title'][:48]}: {errs}")
        else: ok+=1
        if i%25==0: print(f"  ...{i}/{len(plan)}")
        time.sleep(0.55)      # 2 req/s ceiling on the Admin API
    print(f"\n{ok} tagged, {fail} failed.")

if __name__=='__main__': main()
