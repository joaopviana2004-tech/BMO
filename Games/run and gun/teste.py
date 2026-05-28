import ollama
from ollama import Client

DEFAULT_OLLAMA_URL = "https://sternmost-interregional-heath.ngrok-free.dev/"
client = Client(host=DEFAULT_OLLAMA_URL)
messages = [{"role": "system", "content": "voce é um jarvis, assistente virtual, voce nao e autonomo, deve seguir as ordens do usuario, nao faça nada sem permissao ou pedido previo do usuario"}]

def get_weather(city):
    # Aqui você poderia chamar uma API real. Por enquanto, vamos simular:
    if "são paulo" in city.lower():
        return "25°C e ensolarado"
    return "18°C e nublado"

tools = [
    {
        'type': 'function',
        'function': {
            'name': 'get_weather',
            'description': 'Retorna a temperatura atual de uma cidade',
            'parameters': {
                'type': 'object',
                'properties': {
                    'city': {
                        'type': 'string',
                        'description': 'O nome da cidade',
                    },
                },
                'required': ['city'],
            },
        },
    },
]



while True:
    mensagem_user = input("User: ")
    messages.append({"role": "user", "content": mensagem_user})
    response = client.chat(model="gemma3:4b", messages=messages, )

    print(response.message.tool_calls or "Nenhuma Consulta Feita")
    
    # Verifica se o modelo quer chamar uma função
    if response.message.tool_calls:
        for tool in response.message.tool_calls:
            if tool.function.name == 'get_weather':
                cidade = tool.function.arguments.get('city')                
                # Executamos a função Python de verdade
                resultado = get_weather(cidade)

                # Adicionamos a resposta da ferramenta ao histórico
                messages.append(response.message) # Adiciona o pedido do modelo
                messages.append({
                    'role': 'tool',
                    'content': resultado,
                    'name': tool.function.name
                })

        # Chamamos o modelo de novo para ele "ler" o resultado da função e te responder
        final_response = client.chat(model="llama3.1:8b", messages=messages)
        content = final_response.message.content
        print(f"Jarvis: {content}")
        messages.append({"role": "assistant", "content": content})
    
    else:
        # Resposta normal sem uso de ferramentas
        content = response.message.content
        print(f"Jarvis: {content}")
        messages.append({"role": "assistant", "content": content})

    