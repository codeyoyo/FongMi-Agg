import json, re, urllib.request, concurrent.futures as cf
UA={'User-Agent':'Mozilla/5.0 (Linux; Android 12)'}
NAME_KW=['番号','杏吧','奶子','骚','穴','自慰','成人','18禁','porn','AV','色']
CONTENT_KW=['奶','穴','骚','插','射','裸','淫','操','av','porn','无码','内射','口交','巨乳']

def has_kw(t, kws):
    tl=t.lower()
    return any(k.lower() in tl for k in kws)

def check(x):
    name=str(x['name'])
    flag = '