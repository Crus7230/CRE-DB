import requests,re,html,sys,urllib.parse
q=' '.join(sys.argv[1:])
url='https://search.naver.com/search.naver?where=web&query='+urllib.parse.quote(q)
r=requests.get(url,headers={'User-Agent':'Mozilla/5.0'},timeout=30)
print('STATUS',r.status_code,len(r.text),r.url)
for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',r.text,re.S):
    u=html.unescape(m.group(1)); t=re.sub('<[^>]+>',' ',m.group(2)); t=html.unescape(re.sub(r'\s+',' ',t)).strip()
    if t and u.startswith('http'):
        print(t[:140],'\t',u[:300])
