from openai import OpenAI
import numpy as np
import os
# OpenAI API 키 로드
def load_openai_api_key():
    """OPENAI_API.txt 파일에서 API 키 로드"""
    try:
        key_file = os.path.join(os.path.dirname(__file__), "OPENAI_API.txt")
        with open(key_file, 'r') as f:
            key = f.read().strip()
            if key and key != "YOUR_API_KEY_HERE":
                return key
    except FileNotFoundError:
        pass
    
    # 환경 변수에서 시도
    return os.getenv("OPENAI_API_KEY", None)

# OpenAI API 설정
OPENAI_API_KEY = load_openai_api_key()
client = OpenAI(api_key=OPENAI_API_KEY)  # 환경변수 OPENAI_API_KEY 사용

def cosine_similarity(a, b):
    a, b = np.array(a, dtype=float), np.array(b, dtype=float)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

def sentence_similarity(s1: str, s2: str, model="text-embedding-3-small") -> float:
    resp = client.embeddings.create(model=model, input=[s1, s2])
    v1, v2 = resp.data[0].embedding, resp.data[1].embedding
    return cosine_similarity(v1, v2)

print(sentence_similarity("동국대 주변에 분위기 좋은 카페좀 추천해줘", "임지영 국가대표 바리스타가 운영하는 충무로 카페, 헤베커피입니다. 헤베는 매장 한켠에 원두가 한가득 쌓인 로스팅 공간이 있습니다. 거기서 세심하게 볶은 원두로 내린 커피라고 생각하니 더 맛있게 느껴졌습니다. 주변도 조용한 편이고, 매장 내부도 우드톤에 차분하고 편안한 느낌이 들어 좋았습니다. 날 좋을 땐 야외 자리에서 마셔도 좋을 것 같았네요. 여유 있는 분위기라 연인 혹은 소개팅 하시는 분들께 추천드리고 싶네요."))
