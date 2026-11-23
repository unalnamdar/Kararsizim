# Kararsızım — Proje Kılavuzu (Claude Code için)

Bu dosya projenin tek doğruluk kaynağıdır. Her oturumda önce bunu oku. İş **fazlara** bölünmüştür: sana hangi faz söylendiyse yalnızca onu uygula, fazın "Kabul kriterleri" sağlanınca dur ve özet ver. Sonraki faza kendiliğinden geçme.

Kullanım: kullanıcı "Faz 1'i uygula" gibi bir komut verir.

---

## 1. Ürün özeti

**Kararsızım**, kararsız kalan kullanıcıların topluluğa soru sorup anket açtığı bir web uygulamasıdır.

Örnek: "Bugün sinemaya mı gitsem, restorana mı?" → 2–5 seçenek → herkes oylar.

### Kurallar

- Takip mekanizması **yok**. Her anket herkese açıktır; tek bir genel akış vardır.
- **Üye olmayanlar** anketleri görebilir ve oy verebilir.
- **Anket oluşturmak** için üyelik şarttır.
- Kayıtta **e-posta, parola, kullanıcı adı** alınır. Anketlerde yalnızca **kullanıcı adı** görünür; e-posta hiçbir sayfada, HTML'de veya JSON yanıtında yer almaz.
- Bir anket en az **2**, en fazla **5** seçenek içerir.
- Bir kişi bir ankete **tek oy** verir; oy değiştirilemez (prototip).
- Sonuçlar (yüzde + oy sayısı) kişiye **oy verdikten sonra** gösterilir. Anket sahibi sonuçları her zaman görür ve kendi anketine de (herkes gibi tek) oy verebilir (karar 7).
- Anket sahibi anketini **silebilir**, düzenleyemez (oy geldikten sonra soruyu değiştirmek adil olmaz).

### Netleştirilen kararlar (2026-11-17)

1. **Toplam oy sayısı da sonuçtur.** Oy vermemiş kişi hiçbir sayı görmez (toplam dahil); HTML ve JSON'da yer almaz. Kart altında bunun yerine "Oy ver, sonuçları gör" gibi bir metin gösterilir. Sayıları yalnızca oy vermiş kişi ve anket sahibi görür.
2. **Misafir → üye geçişi.** Giriş yapmış kullanıcıda "oy verdi mi?" kontrolü hem `user` hem de tarayıcıdaki `voter_id` çereziyle yapılır. O çerezle daha önce oy verilmişse "zaten oy verdin" sayılır (`409`) ve sonuçlar görünür. Bunun için `voter_id` çerezi üye oylarında da üretilir ve `voter_key` **her oyda** (üye oyu dahil) saklanır; böylece üye oy verip çıkış yaparsa aynı tarayıcıdan misafir olarak tekrar oy veremez. Bedeli: aynı tarayıcıyı paylaşan iki üyeden yalnızca biri aynı ankete oy verebilir (kabul edildi). Çerezi silen herkes (sahip dahil) tekrar oy verebilir — bilinen sınır.
3. **Oy yeri.** Hem akıştaki kartlardan hem detay sayfasından oy verilebilir; sonuçlar kartın içinde yerinde açılır.
4. **Git.** Ana dal `main`, remote `origin` (GitHub: `unalnamdar/Kararsizim`). Her faz kabul kriterleri sağlanınca tek commit atılır ve `main` pushlanır.
5. **Tasarım: kontrast öncelikli palet (Faz 4).** WCAG AA ölçülerek uygulandı (`config/test_design.py` her çalıştırmada denetler). Seçenek **kenarlıkları** arayüz bileşeni sayıldığı için ≥3:1 gerektiriyordu; mercan, turkuaz ve özellikle sarı koyulaştırıldı (sarı kenarlık hardal tonu `#B38500`; çubuk dolgusu ve zemin tonu parlak sarı kalır). Form alanı kenarlığı ve odak halkası da aynı nedenle koyu tonda.
6. **Tasarım: dar ekran başlığı (Faz 4).** 360px'de başlık tek satır kalsın diye: "Anket oluştur" düğmesi "+ Anket"e kısalır, üye menüsü baş harfli yuvarlak düğme olur, misafirde "Kayıt ol" bağlantısı başlıktan kalkar (giriş sayfasındaki "Kayıt ol" bağlantısından erişilir). 30em ve üstünde hepsi tam görünür.
7. **Sahip kendi anketine oy verebilir (2026-11-23, kullanıcı kararı).** Bölüm 1'deki "sahip oy veremez" kuralı kaldırıldı. Sahip sonuçları yine baştan görür; oy vermediği sürece sonuç çubuklarının her biri bir düğmedir ("Sen de oy verebilirsin"). Oy verince diğer herkes gibi tek oyu sayılır (ikinci deneme `409`, çıkış yapıp misafir olarak denemek de aynı tarayıcıda `409`), seçimi ✓ ile görünür ve çubuklar tıklanamaz olur. Diğer ziyaretçiler için hiçbir şey değişmedi: oy vermeden sonuç görmezler.
8. **Faz 6 kapsamı ve kötüye kullanım parametreleri (2026-11-23, kullanıcı kararı).** Şimdi yapılacaklar: kötüye kullanım önlemleri, popüler sıralama + "oylamadıklarım" filtresi, profil sayfası. Parola sıfırlama sonraya. Kötüye kullanım: (a) hız sınırı **uygulamanın içinde, veritabanıyla** sayılır (sunucusuz ortamda bellek içi sayaç çalışmaz): oy 30/dk, kayıt 5/saat, bildirim 10/saat, her biri IP başına; yalnızca **başarılı** eylemler sayılır; aşınca `429` + `Retry-After`. (b) **Yumuşak IP tekilleştirme:** aynı IP özetinden bir ankete en fazla **5** oy (aşınca `403`); "zaten oy verdin" (`409`) bundan önce gelir. (c) IP **ham saklanmaz**: yalnızca `SECRET_KEY`'den türetilen anahtarla HMAC özeti (32 hex; IPv6 /64'e indirgenir). (d) IP yalnızca Vercel'in kendisinin yazdığı `X-Vercel-Forwarded-For`/`X-Forwarded-For` başlıklarından alınır (Vercel bunların üzerine yazar, taklit edilemez); başlık yoksa IP kontrolleri **devre dışı** kalır (yerel geliştirme, test). `REMOTE_ADDR` bilerek kullanılmaz: Vercel arkasında herkes için aynı altyapı adresidir ve sınır tüm siteyi kilitlerdi. (e) **Anket bildirme:** herkes bildirebilir (üye başına ya da IP özeti başına bir kez), sahip kendi anketini bildiremez; bildirimler yalnızca admin panelinde görünür, anket **otomatik gizlenmez**.
9. **Popüler sıralama ve filtre (Faz 6).** "Popüler" = son 7 günde en çok oy alan anket; eşitlikte (ve sıfırda) yeni olan önce. Sıralama, oy vermemiş kişiye anketlerin birbirine göre popülerliğini ima eder ama toplam oy sayısını ya da seçenek sonuçlarını göstermez. "Oylamadıklarım" = üye hesabıyla ya da tarayıcı çereziyle oy verilmemiş anketler (sahibin henüz oy vermediği kendi anketleri dahil). Adres parametreleri: `?sirala=populer`, `?filtre=oylamadiklarim`; "Daha fazla" ikisini de korur. **Profil sayfası:** `/u/<kullaniciadi>/` herkese açık (yalnızca etkin üyeler), üyenin anketleri ve üyelik ayı görünür, e-posta asla; kartlardaki `@kullaniciadi` oraya bağlanır, üye menüsünde "Profilim" vardır.

### Kapsam dışı (prototipte yapma)

Takip, yorum, beğeni, mesajlaşma, bildirim, görsel yükleme, e-posta doğrulama, sosyal giriş, arama, kategori/etiket, anket süresi, admin dışı moderasyon araçları.

---

## 2. Teknoloji

| Katman | Seçim |
|---|---|
| Dil / framework | Python 3.12, Django 5.2 LTS |
| Veritabanı | Supabase (yalnızca **Postgres** olarak; Supabase Auth / JS istemcisi kullanılmaz) |
| DB sürücüsü | `psycopg[binary]` (v3) + `dj-database-url` |
| Kimlik doğrulama | Django'nun kendi auth sistemi (oturum çerezi) |
| Ön yüz | Django template + düz HTML, CSS, JavaScript. Framework, bundler, npm **yok** |
| Deployment | Vercel (Django zero-config desteği) |
| Ortam değişkenleri | `python-dotenv` ile yerelde `.env` |

İlke: **prototip**. Yeni bağımlılık eklemeden önce gerçekten gerekli mi diye sor. DRF, Celery, Redis, React, Tailwind, Docker ekleme.

### Kod kuralları

- Kod, değişken, model ve commit mesajları **İngilizce**; kullanıcıya görünen tüm arayüz metinleri **Türkçe**.
- URL yolları Türkçe (aşağıdaki tabloya bak).
- Ayarlar: `LANGUAGE_CODE = "tr"`, `TIME_ZONE = "Europe/Istanbul"`, `USE_TZ = True`.
- Gizli değerler yalnızca ortam değişkenlerinde: `SECRET_KEY`, `DATABASE_URL`, `DEBUG`. `.env` git'e girmez; `.env.example` girer.
- Her fazda ilgili kısım için Django testleri yaz (`python manage.py test`).

---

## 3. Proje yapısı

```
kararsizim/
├── manage.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── config/              # settings.py, urls.py, wsgi.py
├── accounts/            # özel User modeli, kayıt / giriş / çıkış
├── polls/               # Poll, Option, Vote; akış, detay, oluşturma, oy
├── templates/
│   ├── base.html
│   ├── accounts/
│   └── polls/
└── static/
    ├── css/  (tokens.css, main.css)
    └── js/   (vote.js, poll-form.js)
```

---

## 4. Veri modeli

### accounts.User (`AbstractUser`'dan türet — **ilk migration'dan önce** tanımla)

- `email`: unique, zorunlu. `USERNAME_FIELD = "email"` (giriş e-posta + parola ile).
- `username`: unique (büyük/küçük harf duyarsız), 3–20 karakter, yalnızca `a-z 0-9 _`. Küçük harfe çevirerek kaydet. `REQUIRED_FIELDS = ["username"]`.
- `AUTH_USER_MODEL = "accounts.User"`.

### polls.Poll

- `author` → User (CASCADE)
- `question`: CharField, max 200
- `created_at`: otomatik, indeksli

### polls.Option

- `poll` → Poll (CASCADE, `related_name="options"`)
- `text`: CharField, max 80
- `position`: 0–4 arası sıra

### polls.Vote

- `poll` → Poll, `option` → Option
- `user` → User, **nullable** (üye oyu)
- `voter_key`: CharField(36), **nullable** (anonim ziyaretçi kimliği)
- `created_at`
- Kısıtlar (`UniqueConstraint` + `condition`):
  - `(poll, user)` benzersiz, `user IS NOT NULL` iken
  - `(poll, voter_key)` benzersiz, `voter_key IS NOT NULL` iken
- `option.poll == poll` doğrulaması sunucuda yapılır.

### Anonim oy kimliği

- Oy veren üye değilse, imzalı ve `HttpOnly` bir `voter_id` çerezi (UUID4, 1 yıl, `SameSite=Lax`) üretilir; `voter_key` olarak saklanır.
- Üye giriş yaptıysa oy `user` üzerinden tutulur.
- **Bilinen sınır:** çerezi silen kişi tekrar oy verebilir. Faz 6'da sıkılaştırıldı (karar 8): aynı ağdan bir ankete en fazla 5 oy ve oy/kayıt için hız sınırı; çerezsiz tekil sınırı yine de yoktur.

---

## 5. Sayfalar ve uçlar

| Yol | Yöntem | Erişim | İşlev |
|---|---|---|---|
| `/` | GET | herkes | Akış: en yeni anketler, sayfa başına 20, "Daha fazla" ile sayfalama |
| `/anket/<id>/` | GET | herkes | Anket detayı (paylaşılabilir bağlantı) |
| `/anket/yeni/` | GET, POST | üye | Anket oluşturma formu |
| `/anket/<id>/oy/` | POST (JSON) | herkes | Oy ver. Gövde: `{"option_id": n}` |
| `/anket/<id>/sil/` | POST | sahip | Anketi sil (onay ister) |
| `/anketlerim/` | GET | üye | Kullanıcının kendi anketleri |
| `/kayit/` | GET, POST | misafir | Kayıt (e-posta, kullanıcı adı, parola, parola tekrar) |
| `/giris/` | GET, POST | misafir | Giriş (e-posta, parola) |
| `/cikis/` | POST | üye | Çıkış |
| `/admin/` | — | superuser | Django admin (Poll, Option, Vote, User kayıtlı) |

### Oy ucu sözleşmesi

- Başarılı → `200` `{"total": 42, "options": [{"id": 1, "votes": 30, "percent": 71}, ...], "voted_option_id": 1}`
- Zaten oy verilmiş → `409`, aynı sonuç gövdesiyle
- Geçersiz seçenek → `400`, `{"error": "..."}` (Türkçe mesaj). Anket yoksa `404`. (Sahip oyu artık reddedilmez; karar 7.)
- CSRF koruması açık kalır; `vote.js` token'ı `X-CSRFToken` başlığıyla gönderir.
- Yarış durumunda `IntegrityError` yakalanıp `409` döndürülür.
- Yüzdeler toplamı 100 olacak şekilde yuvarlanır.

### Davranış ayrıntıları

- Giriş yapmamış biri "Anket oluştur"a basarsa `/giris/?next=/anket/yeni/` adresine gider; girişten sonra forma döner.
- Anket formu 2 seçenek alanıyla açılır; "+ Seçenek ekle" ile 5'e kadar çıkar, 2'nin altına inilemez (`poll-form.js`). Aynı kurallar **sunucuda da** doğrulanır; boş ve yinelenen seçenekler reddedilir.
- Akışta N+1 sorgu olmamalı: `select_related("author")`, `prefetch_related("options")`, oy sayıları `annotate` ile; kullanıcının oy verdiği anketler tek sorguyla alınır.
- JavaScript kapalıyken de oy verilebilmeli (form POST → detay sayfasına yönlendirme). JS varsa sayfa yenilenmeden sonuç çubukları animasyonla dolar.

---

## 6. Arayüz yönü

Hedef kitle gençler: **açık zeminli, canlı renklerle tonlanmış, temiz** bir arayüz.

- **Zemin:** kırık beyaz (`#FBFAF7` civarı), kartlar beyaz, yumuşak gölge, 16–20px köşe yarıçapı.
- **Ana renk:** canlı mor (`#6C4DF6` civarı). Düğmeler, bağlantılar, odak halkası.
- **Seçenek paleti (sırayla 5 renk):** mor, mercan, turkuaz, sarı, yeşil. Her seçenek kendi rengini alır: oy öncesi rengin çok açık tonu (≈%10) + renkli kenarlık; oy sonrası sonuç çubuğu o rengin açık tonuyla soldan dolar, yüzde koyu tonla yazılır. Kullanıcının seçtiği seçenek belirgin işaretlenir (✓ + kalın kenarlık).
- **Tipografi:** tek bir yuvarlak hatlı sans (ör. Plus Jakarta Sans, Google Fonts) + sistem yedeği. Soru metni büyük ve kalın.
- **Yerleşim:** mobil öncelikli; tek sütun akış, masaüstünde en fazla ~640px genişlik. Üstte sade bir başlık çubuğu: logo yazısı "Kararsızım", sağda "Anket oluştur" düğmesi + giriş/kayıt ya da kullanıcı adı menüsü.
- **Kart içeriği:** `@kullaniciadi · 3 saat önce`, soru, seçenekler, altta toplam oy sayısı (yalnızca sonuçları görme hakkı olana; bkz. bölüm 1, karar 1).
- **Boş durumlar:** akış boşsa "Henüz anket yok. İlk kararsız sen ol!" + düğme.
- **Erişilebilirlik:** metin kontrastı WCAG AA, klavye ile oy verilebilir, görünür `:focus-visible`, `prefers-reduced-motion` desteklenir. Açık tonlu zeminde metin için her zaman koyu ton kullan.
- Tüm renk, boşluk ve yarıçaplar `tokens.css` içinde CSS değişkeni olarak tanımlanır; `main.css` yalnızca değişkenleri kullanır.

---

## 7. Supabase ve Vercel notları

### Supabase

- Bağlantı yalnızca `DATABASE_URL` ile. Vercel serverless olduğu için **Transaction pooler** (port `6543`) bağlantı dizesi kullanılır.
- Transaction modu prepared statement desteklemez. Ayarlar:

```python
DATABASES = {"default": dj_database_url.config(default="sqlite:///db.sqlite3", conn_max_age=0, ssl_require=not DEBUG)}
if DATABASES["default"]["ENGINE"].endswith("postgresql"):
    DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
    DATABASES["default"].setdefault("OPTIONS", {})["prepare_threshold"] = None
```

- `DATABASE_URL` yoksa yerelde SQLite'a düşülür (hızlı geliştirme için).
- **Migration'lar Vercel build'inde çalıştırılmaz.** Yerelden, `DATABASE_URL` Supabase **Session pooler** (port `5432`) dizesine ayarlıyken `python manage.py migrate` ile uygulanır.
- **Güvenlik:** Django tabloları `public` şemasında oluşur ve Supabase'in Data API'si üzerinden anon anahtarla erişilebilir olabilir. Deployment öncesi ya Data API kapatılır ya da tüm tablolarda RLS açılır (politika eklemeden; Django tablo sahibi olarak bağlandığı için etkilenmez). Faz 5'te bunu kontrol et ve kullanıcıya bildir.

### Vercel

- Güncel yönergeyi uygula: https://vercel.com/docs/frameworks/full-stack/django — kurulumdan önce bu sayfayı oku, eski `vercel.json` + `builds` yöntemlerini kullanma.
- `STATIC_ROOT` tanımlı olmalı; Vercel build sırasında `collectstatic` çalıştırır ve dosyaları CDN'den sunar.
- Ortam değişkenleri (Vercel panelinde): `SECRET_KEY`, `DATABASE_URL` (transaction pooler), `DEBUG=False`.
- `ALLOWED_HOSTS = [".vercel.app", "localhost", "127.0.0.1"]`, `CSRF_TRUSTED_ORIGINS = ["https://*.vercel.app"]`.
- `DEBUG=False` iken: `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`.
- Dosya sistemi kalıcı değildir: yüklenen dosya, SQLite veya dosya tabanlı oturum kullanma.

---

## 8. Fazlar

### Faz 0 — İskelet

**Yap:** git deposu, sanal ortam, `requirements.txt`, Django projesi (`config`), `accounts` ve `polls` uygulamaları, özel `User` modeli (bölüm 4) ve ilk migration, ayarlar (bölüm 2 ve 7), `.env.example`, `.gitignore`, `base.html` + boş bir ana sayfa, kısa `README.md` (kurulum adımları).

**Kabul kriterleri:**
- `python manage.py runserver` SQLite ile hatasız açılır, ana sayfa "Kararsızım" başlığını gösterir.
- `createsuperuser` e-posta + kullanıcı adı + parola sorar; `/admin/` çalışır.
- `python manage.py check --deploy` kritik hata vermez (`DEBUG=False` iken).

### Faz 1 — Üyelik

**Yap:** kayıt, giriş, çıkış sayfaları ve formları; kullanıcı adı doğrulaması; `next` parametresi desteği; başlık çubuğunda oturum durumuna göre bağlantılar; Türkçe hata mesajları (ör. "Bu kullanıcı adı alınmış").

**Kabul kriterleri:**
- Yeni kullanıcı kayıt olunca otomatik giriş yapar ve ana sayfaya döner.
- Aynı e-posta veya aynı kullanıcı adı (büyük/küçük harf farkıyla bile) ikinci kez kullanılamaz.
- Django parola doğrulayıcıları etkin.
- Testler: başarılı kayıt, yinelenen e-posta, yinelenen kullanıcı adı, geçersiz kullanıcı adı, giriş/çıkış.

### Faz 2 — Anket oluşturma ve görüntüleme

**Yap:** `Poll`, `Option` modelleri + migration; anket oluşturma formu (dinamik 2–5 seçenek); akış (`/`), detay sayfası, "Anketlerim", silme; admin kayıtları.

**Kabul kriterleri:**
- Misafir `/anket/yeni/` adresinde girişe yönlendirilir ve girişten sonra forma döner.
- 1 veya 6 seçenekli, boş ya da yinelenen seçenekli istekler sunucuda reddedilir (JS atlatılsa bile).
- Akış en yeni anket üstte olacak şekilde sıralı ve sayfalıdır; sorgu sayısı anket sayısıyla artmaz (testte `assertNumQueries`).
- Yalnızca sahip silebilir; başkası `403` alır.
- Hiçbir sayfa çıktısında e-posta geçmez (test et).

### Faz 3 — Oylama

**Yap:** `Vote` modeli + kısıtlar; anonim `voter_id` çerezi; oy ucu (bölüm 5 sözleşmesi); `vote.js`; sonuç gösterimi kuralları; JS'siz yedek akış.

**Kabul kriterleri:**
- Misafir ve üye oy verebilir; aynı kişi ikinci kez veremez (`409`).
- Oy vermeden önce sonuçlar HTML'de ve JSON'da **yer almaz**; verdikten sonra görünür ve sayfa yenilenince korunur.
- Sahip kendi anketinde sonuçları baştan görür ve (tek) oy verebilir; oy verince seçimi ✓ ile işaretlenir ve çubuklar tıklanamaz olur (karar 7).
- Başka bir ankete ait `option_id` reddedilir.
- Testler: üye oyu, anonim oy, çift oy, yanlış seçenek, sahip oyu, yüzde toplamı = 100.

### Faz 4 — Arayüz cilası

**Yap:** bölüm 6'daki tasarımın tamamı: `tokens.css`, kart ve seçenek bileşenleri, sonuç çubuğu animasyonu, formlar, boş durumlar, hata/başarı mesajları, 404 ve 500 sayfaları, favicon, sayfa başlıkları ve detay sayfası için Open Graph etiketleri (paylaşım önizlemesi).

**Kabul kriterleri:**
- 360px genişlikte yatay kaydırma yok; masaüstünde içerik ortalı.
- Tüm etkileşimler klavyeyle yapılabilir; kontrast AA.
- Renkler yalnızca CSS değişkenlerinden gelir.

### Faz 5 — Yayın

**Yap:** Supabase'e migration (session pooler ile), RLS / Data API kontrolü, Vercel yapılandırması (güncel dokümana göre), ortam değişkenleri listesi, üretim güvenlik ayarları, README'ye yayın adımları. Kullanıcının panelde elle yapması gereken adımları numaralı liste olarak ver; gizli anahtarları kendin üretip dosyaya yazma.

**Kabul kriterleri:**
- Yayındaki adreste kayıt → anket oluşturma → başka tarayıcıdan misafir oyu uçtan uca çalışır.
- Statik dosyalar yüklenir, `DEBUG=False`, admin erişilebilir.
- Supabase tabloları anon anahtarla okunamaz.

### Faz 6 — Sonrası (ayrı ayrı, istenirse)

Öncelik sırasıyla öneriler:
1. Parola sıfırlama (e-posta gönderimi gerekir).
2. ✅ Kötüye kullanım önlemleri: oy ve kayıt için hız sınırı, IP özeti ile ek tekilleştirme, anket bildirme (karar 8).
3. ✅ Akışta "Popüler" sıralaması ve "oylamadıklarım" filtresi.
4. ✅ Kullanıcı profil sayfası (`/u/<kullaniciadi>/`).
5. Anket bitiş süresi, oy değiştirme.
6. E-posta doğrulama, özel alan adı.
