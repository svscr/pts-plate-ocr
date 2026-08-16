# PTS Plaka OCR Yardımcı Uygulaması

PTS veritabanına, API'sine, dosyalarına veya plaka giriş alanına dokunmadan görünen araç fotoğrafını yerel olarak okuyan Windows tray uygulaması.

## Güvenlik sınırı

Uygulama yalnız kullanıcı kayıtlı OCR kısayoluna bastığında görünür ekran piksellerini yakalar. PTS'ye tıklamaz, yazı yazmaz, `Ctrl+V` göndermediği gibi PTS veritabanı/API/dosyalarına erişmez. Yüksek güvenli sonuç panoya kopyalanır; diğerleri popup'ta kullanıcı onayı bekler.

Plaka çıktısı ve pano biçimi boşluksuzdur: `35CZB379`, `20F8849`.

## İlk kullanım

1. PTS'de araç fotoğrafını açın ve görünür bırakın.
2. Uygulama klasöründeki `PTSPlateOCR.exe` dosyasını çalıştırın.
3. Başlangıçta `Ctrl+Alt+P` ile tarama yapın. Varsayılan ROI, sağlanan 1920×1080 ParkMatik görüntüsündeki fotoğraf penceresine göre hazırlanmıştır.
4. Fotoğraf penceresi farklı yerdeyse tray simgesine sağ tıklayıp **Fotoğraf / plaka alanını kalibre et** seçin. Önce fotoğrafın tamamını, sonra plakanın gelebileceği geniş bandı çizin.
5. Sonuç yüksek güvenliyse pano otomatik güncellenir. Düşük güvende sonucu düzeltip **Panoya kopyala** seçin.

Hotkey ayarlardan kaydedilir: kutuya tıklayıp `Ctrl+Alt+P` gibi bir kombinasyona basın. `A-Z`, `0-9`, `Space` ve `F1`–`F24` desteklenir; harf/rakam için Ctrl, Alt veya Shift gerekir. Seçilen kombinasyon doluysa önceki kayıt korunur ve tray bildirimi gösterilir.

## Geliştirme

Bu çalışma alanındaki ortak virtual environment kullanılabilir:

```powershell
..\.venv\Scripts\python.exe -m pip install -e .
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m ruff check src tests
```

OCR değerlendirmesi için `data/manifest.example.csv` dosyasını kopyalayıp kendi resimlerinizi ve doğru plakaları ekleyin:

```powershell
..\.venv\Scripts\pts-plate-ocr-eval.exe --manifest data\manifest.csv --out reports\evaluation.csv
```

Türkçe karakter içeren Windows dosya adları evaluator tarafından desteklenir.

## Portable paket

```powershell
.\scripts\build-portable.ps1
```

Çıktı doğrudan `..\outputs\PTSPlateOCR\PTSPlateOCR.exe` olur; ZIP oluşturulmaz. `onedir` paket biçimi kullanılır: OCR model dosyaları doğrudan uygulama klasöründe yer alır; Python kurulumu hedef bilgisayarda gerekmez.

## Tanılama ve gizlilik

Loglar `%LOCALAPPDATA%\PTSPlateOCR\logs\app.log` altında tutulur. Debug görüntüleri varsayılan olarak kapalıdır. Ayarlardan açılırsa yalnız yerelde saklanır ve yedi gün veya 500 MB sınırında temizlenir. Ağ telemetrisi veya bulut OCR kullanılmaz.

## Bilinen MVP sınırları

- Tek satırlı standart sivil Türk plakaları hedeflenir.
- Motosiklet, diplomatik, resmi ve iki satırlı plakalar kapsam dışıdır.
- PTS fotoğrafı hotkey anında görünür olmalıdır; başka bir pencere görüntüyü kapatırsa uygulama yalnız görünen pikselleri okuyabilir.
- İlk model modeli yükleme birkaç saniye sürebilir. Sonraki taramalar hedefi yaklaşık bir saniyedir; gerçek veri setiyle tekrar ölçülmelidir.
