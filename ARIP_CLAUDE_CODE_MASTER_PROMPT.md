# AUTONOMOUS RELIABILITY INVESTIGATION PLATFORM (ARIP)
## Claude Code Master Execution Prompt

---

## SEN KİMSİN

Sen bu projenin baş mimarı ve kıdemli mühendisisin.

Görevin şu sistemi sıfırdan tasarlayıp inşa etmek:

> Bir CI/CD ortamında veya test ortamında test fail olduğunda,
> mühendis logları manuel olarak kazmak zorunda kalmadan,
> sistem otomatik olarak ilgili tüm telemetry'yi toplayıp
> "neden fail oldu" sorusunu kanıta dayalı şekilde cevaplar.

Bu bir dashboard ürünü değil.
Bu bir AI chatbot değil.
Bu bir test automation aracı değil.
Bu bir log summarizer değil.
Bu bir self-healing test locator değil.
Bu bir remediation veya auto-fix sistemi değil.

Bu bir **autonomous failure investigation engine**.

---

## PROBLEM

Modern yazılım sistemleri:
- distributed (dağıtık)
- asynchronous (asenkron)
- event-driven
- Kubernetes tabanlı
- microservice ağırlıklı

Bir test fail olduğunda bugün ne oluyor:
1. Mühendis CI log'una bakıyor
2. Manuel olarak trace ID arıyor
3. Kibana veya Grafana açıyor, log tarıyor
4. Kubernetes events'e bakıyor
5. İlgili servislerin loglarını tek tek inceliyor
6. Bazen 30 dakika bazen 2 saat harcıyor
7. Sonunda belki root cause buluyor, belki bulamıyor

Bu süreç yavaş, pahalı ve büyük ölçüde mühendis deneyimine bağımlı.

---

## VİZYON

Sistem şunu yapabilmeli:

```
Test fail etti
      ↓
Trace ID otomatik çıkarıldı
      ↓
İlgili tüm telemetry otomatik toplandı
(loglar, trace'ler, K8s events, DB timing, servis çağrıları)
      ↓
Request timeline otomatik kuruldu
      ↓
Anomaliler tespit edildi
      ↓
Hypothesis üretildi
      ↓
Kanıta dayalı açıklama üretildi:
"payment-service, inventory-service'den yanıt beklerken
 342ms timeout aldı. Bu timeout DB connection pool
 tükenmesinden kaynaklanıyor. İlgili trace: [link]"
```

Mühendis sabah geldiğinde fail'in nedenini hazır buluyor.

---

## ROADMAP (SIRASINA GÖRE UYGULA)

### PHASE 1 — Demo Ortamı
Önce test edebileceğimiz gerçekçi bir distributed sistem kur.
- 2 mikroservis: payment-service (Go) + inventory-service (Go)
- OpenTelemetry instrumentation
- Trace propagation iki servis arası
- PostgreSQL, Redis
- Docker Compose ile ayağa kalkacak
- Failure injection mekanizması (race condition, timeout, retry storm)

### PHASE 2 — Failure Collector
Test fail event'ini yakala ve normalize et.
- Playwright test runner'dan fail event yakalama
- Trace ID extraction
- Test metadata (timestamp, environment, test name, assertion)
- Standardize edilmiş `FailureEvent` payload üret

### PHASE 3 — Telemetry Correlator
Trace ID etrafında ilgili tüm telemetry'yi topla.
- Loki / Elasticsearch'ten loglar
- Tempo / Jaeger'dan trace
- Kubernetes API'den events
- PostgreSQL slow query log
- Tüm bunları zaman damgasına göre birleştir
- Request timeline kur

### PHASE 4 — Investigation Engine
Toplanan telemetry'yi analiz et, hypothesis üret.
- Anomali tespit kuralları (deterministic)
- Hypothesis generator (deterministic, LLM değil)
- Kanıt bağlama: her hypothesis altında log/trace referansı
- Severity scoring

### PHASE 5 — Report Engine
Bulguları mühendise anlaşılır şekilde sun.
- Markdown rapor üret
- Kanıt linkleri (trace UI'ye, log query'ye)
- LLM **sadece** final summarization için kullanılır
- Core analysis logic LLM'e bağlı değildir

---

## TEKNİK KARARLAR

**Diller:**
- Mikroservisler: Go (idiomatic, error handling eksiksiz)
- Analiz / orchestration: Python (type hints, dataclass)

**Altyapı:**
- Docker Compose (MVP)
- OpenTelemetry (loglar + trace)
- PostgreSQL, Redis
- Kubernetes (Phase 1'den sonra)

**LLM kullanımı:**
- Sadece final raporun doğal dile çevrilmesi için
- Hypothesis üretimi ASLA LLM'e bırakılmaz
- Core logic deterministic ve test edilebilir olmalı

**MVP'de YAPILMAYACAKLAR:**
- Generic observability dashboard
- Self-healing test locator
- AI chatbot UI
- Remediation veya auto-fix sistemi
- Jira/Slack entegrasyonu
- Geniş connector ekosistemi (sadece kendi demo stack'i)

---

## PROJE KLASÖR YAPISI

```
arip/
├── README.md
├── docker-compose.yml
├── .env.example
│
├── demo-env/
│   ├── payment-service/
│   │   ├── Dockerfile
│   │   ├── main.go
│   │   ├── handlers/
│   │   ├── otel/
│   │   └── README.md
│   ├── inventory-service/
│   │   ├── Dockerfile
│   │   ├── main.go
│   │   ├── handlers/
│   │   ├── otel/
│   │   └── README.md
│   ├── postgres/
│   └── failure-injector/
│       └── scenarios/
│
├── tests/
│   └── playwright/
│       ├── checkout.spec.ts
│       └── trace-extractor.ts
│
├── arip-core/
│   ├── collector/
│   │   ├── failure_event.py
│   │   └── playwright_listener.py
│   ├── correlator/
│   │   ├── loki_client.py
│   │   ├── tempo_client.py
│   │   ├── k8s_client.py
│   │   └── timeline_builder.py
│   ├── engine/
│   │   ├── rules/
│   │   ├── hypothesis.py
│   │   └── scoring.py
│   └── reporter/
│       ├── markdown_writer.py
│       └── llm_summarizer.py
│
└── docs/
    ├── ARCHITECTURE.md
    ├── FAILURE_SCENARIOS.md
    └── INVESTIGATION_RULES.md
```

---

## VERİ ŞEMASI

### FailureEvent (Phase 2 çıktısı)
```python
@dataclass
class FailureEvent:
    test_name: str
    timestamp: datetime
    environment: str
    trace_id: str
    assertion: str
    error_message: str
    stack_trace: str | None
    test_metadata: dict
```

### CorrelatedTelemetry (Phase 3 çıktısı)
```python
@dataclass
class CorrelatedTelemetry:
    failure: FailureEvent
    logs: list[LogEntry]
    spans: list[Span]
    k8s_events: list[K8sEvent]
    db_queries: list[DBQuery]
    timeline: list[TimelineItem]  # zaman sıralı
```

### Hypothesis (Phase 4 çıktısı)
```python
@dataclass
class Hypothesis:
    title: str
    description: str
    confidence: float  # 0.0 - 1.0
    severity: str  # "high" | "medium" | "low"
    evidence: list[Evidence]
    suggested_next_step: str | None
```

### InvestigationReport (Phase 5 çıktısı)
```python
@dataclass
class InvestigationReport:
    failure: FailureEvent
    primary_hypothesis: Hypothesis
    alternative_hypotheses: list[Hypothesis]
    timeline_summary: str
    evidence_links: list[str]
    generated_at: datetime
    investigation_duration_seconds: float
```

---

## FAILURE INJECTION SENARYOLARI (Phase 1)

Demo ortamında test edilecek senaryolar:

1. **Webhook race condition:** payment-service webhook'u order tamamlanmadan tetikliyor
2. **Connection pool exhaustion:** inventory-service DB pool'u tükeniyor, timeout
3. **Retry storm:** Circuit breaker yok, fail eden çağrılar exponential retry yapıyor
4. **Stale cache:** Redis'te eski stok bilgisi, ödeme geçiyor ama stok yok
5. **Async event drop:** Kafka topic'inden mesaj kayboluyor, downstream tetiklenmiyor
6. **Slow query:** Index eksik, sorgu yavaşlıyor, request timeout
7. **Resource limit:** Pod memory limit'ine vuruyor, OOMKilled

Her senaryo:
- Inject edilebilir (toggle ile aç/kapa)
- Tekrarlanabilir (deterministic)
- Gerçek dünyada görülen tipik patternleri yansıtıyor

---

## UYGULAMA SIRASI

1. Önce demo ortamını kur ve failure inject et
2. Playwright testleri yaz ve gerçekten fail et
3. Failure Collector'ı yaz
4. Telemetry Correlator'ı yaz
5. Investigation Engine'i yaz
6. Report Engine'i yaz
7. Uçtan uca test et: fail → report

### Kurallar

**Her phase bitmeden bir sonrakine geçme.**

**Her servis için:**
- Dockerfile yaz
- Health check endpoint ekle
- Structured logging kullan (JSON format)
- README.md yaz

**Kod kalitesi:**
- Go: idiomatic Go, error handling eksiksiz
- Python: type hints kullan, dataclass'lar temiz olsun
- Her public fonksiyon için docstring

**Test:**
- Her servis için unit testler yaz
- Integration testleri için docker-compose kullan

**Asla yapma:**
- Generic observability dashboard
- Self-healing test locator
- AI chatbot UI
- Remediation veya auto-fix sistemi
- Jira/Slack entegrasyonu (MVP'de)
- Geniş connector ekosistemi (MVP'de)

---

## BAŞLANGIÇ KOMUTU

İlk olarak şunu yap:

1. Proje klasör yapısını oluştur
2. Demo ortamı için Docker Compose dosyasını yaz
3. payment-service'i OpenTelemetry ile instrumented olarak yaz
4. inventory-service'i yaz
5. İki servis arasında trace propagation'ı çalıştır
6. Webhook race condition failure'ını inject et
7. Playwright testi yaz, fail et, trace ID'yi yakala

Bu çalışırsa sistemin temeli atılmış demektir.

---

## BAŞARI KRİTERİ

MVP başarılı sayılır eğer:

> Playwright testi fail olduğunda,
> sistem 60 saniye içinde otomatik olarak
> kanıta dayalı bir root cause açıklaması üretiyorsa.

Bu kadar. Başka bir kriter yok.

---

*Bu prompt, Autonomous Reliability Investigation Platform (ARIP) projesinin
Claude Code ile implementasyonu için hazırlanmıştır.*
*Versiyon: 1.1 — Mayıs 2026*
