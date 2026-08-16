# Test verisi

Özel PTS görüntülerini git veya dağıtım paketine eklemeyin. Bunları `data/private/` altında tutun; klasör `.gitignore` içindedir.

Her yeni görüntü için manifestte şunlar bulunmalıdır:

- `image_path`: manifest dosyasına göre resim yolu
- `expected_plate`: örneğin `35CZB379` (boşluklu eski etiketler de evaluator tarafından kabul edilir)
- `split`: `train`, `validation` veya kilitli `test`
- `capture_session`: aynı aracın ardışık karelerinin aynı split'te tutulması için oturum kimliği
- `conditions`: örneğin `headlight_glare`, `small_plate`, `blur`, `low_light`

Release hedefi, kilitli test setinde genel exact-match en az %95 ve yüksek-güvenli otomatik kopyalarda yanlış sonuç olmamasıdır.
