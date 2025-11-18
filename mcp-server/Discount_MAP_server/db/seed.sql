-- ================================================
--  Discount_MAP_server MVP Mock Data
--  PostgreSQL 12+ compatible
-- ================================================

-- ⚠️ 기존 데이터 초기화 (주의: 실제 서비스 DB에서는 삭제 금지)
TRUNCATE discount_required_affiliation,
         discount_required_membership,
         discount_required_telco,
         discount_required_payment,
         discount_applicable_branch,
         discount_applicable_brand,
         discount_per_unit_rule,
         discount_program,
         payment_product,
         membership_provider_detail,
         affiliation_provider_detail,
         telco_provider_detail,
         payment_provider_detail,
         discount_provider,
         brand_branch,
         brand
RESTART IDENTITY CASCADE;
-- ================================================
-- 1️⃣ 브랜드 / 지점 (동국대 근처 5개)
-- ================================================

INSERT INTO brand (brand_name, brand_owner)
VALUES
('스타벅스', 'SCK컴퍼니'),
('이디야커피', '이디야'),
('던킨도너츠', 'SPC'),
('파리바게뜨', 'SPC'),
('맥도날드', '맥도날드코리아');

-- 지점 (동국대 근처, 실제 위치 기반)
INSERT INTO brand_branch (brand_id, branch_name, latitude, longitude, is_active)
VALUES
(1, '동국대점', 37.5584, 126.9986, TRUE),
(2, '충무로역점', 37.5612, 126.9959, TRUE),
(3, '충무로역점', 37.5601, 126.9964, TRUE),
(4, '장충동점', 37.5573, 127.0015, TRUE),
(5, '퇴계로점', 37.5618, 126.9978, TRUE);

-- ================================================
-- 2️⃣ 할인 제공자 (통신사 / 멤버십 / 카드)
-- ================================================

INSERT INTO discount_provider (provider_name, provider_type, app_coupon, website_url, is_active)
VALUES
-- 통신 3사
('SKT', 'TELCO', FALSE, 'https://www.sktmembership.co.kr', TRUE),
('KT', 'TELCO', FALSE, 'https://membership.kt.com', TRUE),
('LG U+', 'TELCO', FALSE, 'https://www.uplus.co.kr/membership', TRUE),

-- 멤버십 3종
('CJ ONE', 'MEMBERSHIP', FALSE, 'https://www.cjone.com', TRUE),
('L.POINT', 'MEMBERSHIP', FALSE, 'https://www.lpoint.com', TRUE),
('해피포인트', 'MEMBERSHIP', FALSE, 'https://www.happypointcard.com', TRUE),

-- 카드 4종
('우리카드', 'PAYMENT', FALSE, 'https://pc.wooricard.com', TRUE),
('신한카드', 'PAYMENT', FALSE, 'https://www.shinhancard.com', TRUE),
('씨티카드', 'PAYMENT', FALSE, 'https://www.citibank.co.kr', TRUE),
('현대카드', 'PAYMENT', FALSE, 'https://www.hyundaicard.com', TRUE);

-- ================================================
-- 3️⃣ 프로바이더 상세
-- ================================================

-- 결제수단 상세
INSERT INTO payment_provider_detail (provider_id, card_company_code)
VALUES
(8, 'WOORI'),
(9, 'SHINHAN'),
(10, 'HYUNDAI'),
(11, 'BC');

-- 통신사 상세
INSERT INTO telco_provider_detail (provider_id, membership_level_required, telco_name, telco_app_name)
VALUES
(1, 'BASIC', 'SKT', 'T 멤버십'),
(2, 'BASIC', 'KT', 'KT 멤버십'),
(3, 'BASIC', 'LG U+', 'U+ 멤버스');

-- 멤버십 상세
INSERT INTO membership_provider_detail (provider_id, membership_name, membership_level_required)
VALUES
(4, 'CJ ONE', 'BASIC'),
(5, 'L.POINT', 'BASIC'),
(6, '신세계포인트', 'BASIC'),
(7, '해피포인트', 'BASIC');

-- ================================================
-- 4️⃣ 결제수단 메타
-- ================================================

INSERT INTO payment_product (provider_id, payment_name, payment_company)
VALUES
(8, '카드의정석 NEW우리V카드', '우리카드'),
(9, '신한카드 YOLO Tasty', '신한카드'),
(10, 'M', '현대카드'),
(11, 'BLISS.7 카드', 'bc카드');

-- ================================================
-- 5️⃣ F&B 브랜드 추가 (카드 혜택 대상 가맹점)
-- ================================================

INSERT INTO brand (brand_name, brand_owner)
VALUES
  ('아웃백 스테이크하우스', NULL),
  ('애슐리', NULL),
  ('TGIF', NULL),
  ('매드포갈릭', NULL),
  ('피자헛', NULL),
  ('토다이', NULL),
  ('불고기브라더스', NULL),
  ('탐앤탐스', NULL),
  ('삼원가든', 'SG다인힐'),
  ('붓처스컷', 'SG다인힐'),
  ('투뿔등심', 'SG다인힐'),
  ('블루밍가든', 'SG다인힐'),
  ('오스테리아 꼬또', 'SG다인힐'),
  ('썬더버드', 'SG다인힐'),
  ('로스옥', 'SG다인힐')
ON CONFLICT (brand_name) DO NOTHING;

-- ================================================
-- 6️⃣ F&B 할인 프로그램 (discount_program)
--   - is_discount = TRUE : 할인형
--   - is_discount = FALSE : 적립형
-- ================================================

-- 6-1. 카드의정석 NEW우리V카드 - 패밀리레스토랑 25% 청구할인
INSERT INTO discount_program (
  provider_id,
  discount_name,
  discount_type,
  discount_amount,
  max_amount,
  max_usage_cnt,
  required_level,
  valid_from,
  valid_to,
  dow_mask,
  time_from,
  time_to,
  channel_limit,
  qualification,
  application_menu,
  is_active,
  is_discount
)
SELECT
  p.provider_id,
  'NEW 우리V카드 패밀리레스토랑 25% 청구할인',
  'PERCENT',
  25.0,
  25000,   -- 건당 최대 25,000원
  NULL,    -- 월 사용 횟수 제한 명시 X
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'OFFLINE',
  '전월 국내가맹점 이용액 30만원 이상 시 제공. 아웃백, 애슐리, TGIF, 매드포갈릭, 피자헛(매장방문 결제), 토다이 25% 청구할인. 토다이 할인서비스는 1일 1회 제공. 백화점/대형마트·미군부대 내 매장 제외.',
  '패밀리레스토랑·피자 전문점',
  TRUE,
  TRUE
FROM discount_provider p
WHERE p.provider_name = '우리카드'
  AND NOT EXISTS (
    SELECT 1 FROM discount_program dp
    WHERE dp.discount_name = 'NEW 우리V카드 패밀리레스토랑 25% 청구할인'
  );

-- 6-2. 카드의정석 NEW우리V카드 - 불고기브라더스 20% 현장할인
INSERT INTO discount_program (
  provider_id,
  discount_name,
  discount_type,
  discount_amount,
  max_amount,
  max_usage_cnt,
  required_level,
  valid_from,
  valid_to,
  dow_mask,
  time_from,
  time_to,
  channel_limit,
  qualification,
  application_menu,
  is_active,
  is_discount
)
SELECT
  p.provider_id,
  'NEW 우리V카드 불고기브라더스 20% 현장할인',
  'PERCENT',
  20.0,
  20000,   -- 건당 최대 20,000원
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'OFFLINE',
  '전월 국내가맹점 이용액 30만원 이상 시 제공. 불고기브라더스 20% 현장할인, 건당 최대 2만원. 토다이와 불고기브라더스 할인은 1일 1회 제공. 패밀리레스토랑 자체 정책에 따라 다른 서비스와 중복 할인 불가, 주류·도시락 등 일부 상품 제외.',
  '패밀리레스토랑(불고기브라더스)',
  TRUE,
  TRUE
FROM discount_provider p
WHERE p.provider_name = '우리카드'
  AND NOT EXISTS (
    SELECT 1 FROM discount_program dp
    WHERE dp.discount_name = 'NEW 우리V카드 불고기브라더스 20% 현장할인'
  );

-- 6-3. 카드의정석 NEW우리V카드 - 탐앤탐스/스타벅스 20% 청구할인
INSERT INTO discount_program (
  provider_id,
  discount_name,
  discount_type,
  discount_amount,
  max_amount,
  max_usage_cnt,
  required_level,
  valid_from,
  valid_to,
  dow_mask,
  time_from,
  time_to,
  channel_limit,
  qualification,
  application_menu,
  is_active,
  is_discount
)
SELECT
  p.provider_id,
  'NEW 우리V카드 탐앤탐스/스타벅스 20% 청구할인',
  'PERCENT',
  20.0,
  5000,   -- 월 최대 5,000원까지 할인
  2,      -- 월 2회
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  '전월 국내가맹점 이용액 30만원 이상 시 제공. 탐앤탐스, 스타벅스 20% 청구할인 (통합 일 1회, 월 2회, 월 최대 5천원). 커피 브랜드의 상품권·선불카드 구입/충전, 타 가맹점 명의 매장, 백화점/대형마트·미군부대 내 매장 제외.',
  '커피전문점(탐앤탐스, 스타벅스)',
  TRUE,
  TRUE
FROM discount_provider p
WHERE p.provider_name = '우리카드'
  AND NOT EXISTS (
    SELECT 1 FROM discount_program dp
    WHERE dp.discount_name = 'NEW 우리V카드 탐앤탐스/스타벅스 20% 청구할인'
  );

-- 6-4. 신한카드 YOLO Tasty - SG다인힐 외식업체 10% 결제일 할인
INSERT INTO discount_program (
  provider_id,
  discount_name,
  discount_type,
  discount_amount,
  max_amount,
  max_usage_cnt,
  required_level,
  valid_from,
  valid_to,
  dow_mask,
  time_from,
  time_to,
  channel_limit,
  qualification,
  application_menu,
  is_active,
  is_discount
)
SELECT
  p.provider_id,
  'YOLO Tasty SG다인힐 10% 결제일 할인',
  'PERCENT',
  10.0,
  10000,   -- 할인 전 승인금액 10만원까지 → 최대 10,000원 할인
  3,       -- 통합 월 3회
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  'SG다인힐 외식업체(삼원가든, 붓처스컷, 투뿔등심, 블루밍가든, 오스테리아 꼬또, 썬더버드, 로스옥) 10% 결제일 할인. 통합 월 3회, 할인 전 승인금액 10만원까지 할인 적용.',
  'SG다인힐 외식업체',
  TRUE,
  TRUE
FROM discount_provider p
WHERE p.provider_name = '신한카드'
  AND NOT EXISTS (
    SELECT 1 FROM discount_program dp
    WHERE dp.discount_name = 'YOLO Tasty SG다인힐 10% 결제일 할인'
  );

-- ================================================
-- 7️⃣ discount_required_payment : 할인 ↔ 카드상품 매핑
-- ================================================

-- NEW우리V카드 3개 혜택
INSERT INTO discount_required_payment (discount_id, payment_id)
SELECT dp.discount_id, pp.payment_id
FROM discount_program dp
JOIN payment_product pp
  ON pp.payment_name = '카드의정석 NEW우리V카드'
WHERE dp.discount_name IN (
  'NEW 우리V카드 패밀리레스토랑 25% 청구할인',
  'NEW 우리V카드 불고기브라더스 20% 현장할인',
  'NEW 우리V카드 탐앤탐스/스타벅스 20% 청구할인'
)
AND NOT EXISTS (
  SELECT 1 FROM discount_required_payment drp
  WHERE drp.discount_id = dp.discount_id
    AND drp.payment_id = pp.payment_id
);

-- YOLO Tasty SG다인힐
INSERT INTO discount_required_payment (discount_id, payment_id)
SELECT dp.discount_id, pp.payment_id
FROM discount_program dp
JOIN payment_product pp
  ON pp.payment_name = '신한카드 YOLO Tasty'
WHERE dp.discount_name = 'YOLO Tasty SG다인힐 10% 결제일 할인'
AND NOT EXISTS (
  SELECT 1 FROM discount_required_payment drp
  WHERE drp.discount_id = dp.discount_id
    AND drp.payment_id = pp.payment_id
);

-- ================================================
-- 8️⃣ discount_applicable_brand : 할인 ↔ 브랜드 매핑
-- ================================================

-- 8-1. NEW 우리V카드 패밀리레스토랑 25% 청구할인
INSERT INTO discount_applicable_brand (discount_id, brand_id, is_excluded)
SELECT dp.discount_id, b.brand_id, FALSE
FROM discount_program dp
JOIN brand b ON b.brand_name IN (
  '아웃백 스테이크하우스',
  '애슐리',
  'TGIF',
  '매드포갈릭',
  '피자헛',
  '토다이'
)
WHERE dp.discount_name = 'NEW 우리V카드 패밀리레스토랑 25% 청구할인'
  AND NOT EXISTS (
    SELECT 1 FROM discount_applicable_brand dab
    WHERE dab.discount_id = dp.discount_id
      AND dab.brand_id = b.brand_id
  );

-- 8-2. NEW 우리V카드 불고기브라더스 20% 현장할인
INSERT INTO discount_applicable_brand (discount_id, brand_id, is_excluded)
SELECT dp.discount_id, b.brand_id, FALSE
FROM discount_program dp
JOIN brand b ON b.brand_name = '불고기브라더스'
WHERE dp.discount_name = 'NEW 우리V카드 불고기브라더스 20% 현장할인'
  AND NOT EXISTS (
    SELECT 1 FROM discount_applicable_brand dab
    WHERE dab.discount_id = dp.discount_id
      AND dab.brand_id = b.brand_id
  );

-- 8-3. NEW 우리V카드 탐앤탐스/스타벅스 20% 청구할인
INSERT INTO discount_applicable_brand (discount_id, brand_id, is_excluded)
SELECT dp.discount_id, b.brand_id, FALSE
FROM discount_program dp
JOIN brand b ON b.brand_name IN ('탐앤탐스', '스타벅스')
WHERE dp.discount_name = 'NEW 우리V카드 탐앤탐스/스타벅스 20% 청구할인'
  AND NOT EXISTS (
    SELECT 1 FROM discount_applicable_brand dab
    WHERE dab.discount_id = dp.discount_id
      AND dab.brand_id = b.brand_id
  );

-- 8-4. YOLO Tasty SG다인힐 10% 결제일 할인
INSERT INTO discount_applicable_brand (discount_id, brand_id, is_excluded)
SELECT dp.discount_id, b.brand_id, FALSE
FROM discount_program dp
JOIN brand b ON b.brand_name IN (
  '삼원가든',
  '붓처스컷',
  '투뿔등심',
  '블루밍가든',
  '오스테리아 꼬또',
  '썬더버드',
  '로스옥'
)
WHERE dp.discount_name = 'YOLO Tasty SG다인힐 10% 결제일 할인'
  AND NOT EXISTS (
    SELECT 1 FROM discount_applicable_brand dab
    WHERE dab.discount_id = dp.discount_id
      AND dab.brand_id = b.brand_id
  );
