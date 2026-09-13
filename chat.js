// This runs on Vercel's servers, never in the user's browser.
// Your Gemini API key stays here, safe, and is never sent to anyone visiting the site.
// Google AI Studio's free tier needs no credit card — see console.cloud... actually aistudio.google.com

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) {
    return res.status(500).json({ error: 'Server is not configured with an API key yet.' });
  }

  try {
    const { system, messages, image_base64, function_call, function_result, json_mode } = req.body;

    // Convert the Claude-style messages array into Gemini's "contents" format
    const contents = (messages || []).map(m => ({
      role: m.role === 'assistant' ? 'model' : 'user',
      parts: [{ text: m.content }]
    }));

    // If the Jarvis Bridge sent a screenshot with the ORIGINAL message, attach
    // it directly (used by the manual "Scan my screen" button).
    if (image_base64 && contents.length) {
      contents[contents.length - 1].parts.push({
        inline_data: { mime_type: 'image/png', data: image_base64 }
      });
    }

    // If the model already asked to run a tool and the frontend has executed
    // it, append that round trip so Gemini can give a final, grounded reply.
    if (function_call && function_result) {
      contents.push({ role: 'model', parts: [{ functionCall: function_call }] });
      if (function_result.image_base64) {
        // Screen scans: just hand the model the actual image to look at.
        contents.push({
          role: 'user',
          parts: [
            { text: 'Here is a screenshot of what is currently on my screen.' },
            { inline_data: { mime_type: 'image/png', data: function_result.image_base64 } }
          ]
        });
      } else {
        contents.push({
          role: 'user',
          parts: [{
            functionResponse: {
              name: function_call.name,
              response: {
                ok: function_result.ok,
                message: function_result.message,
                ...(function_result.data ? { data: function_result.data } : {})
              }
            }
          }]
        });
      }
    }

    // The 3 named tools above (custom, from the Jarvis Bridge) PLUS Gemini's own
    // built-in Google Search grounding — this is the same mechanism Jarvis's
    // own web_search.py actually uses for news/current events, rather than a
    // separate hand-built scraper.
    const tools = json_mode ? undefined : [
      { googleSearch: {} },
      { functionDeclarations: [
        {
          name: 'open_website',
          description: "Open a website in the user's default browser, on the user's own computer.",
          parameters: {
            type: 'object',
            properties: { url: { type: 'string', description: 'The website URL or domain to open, e.g. youtube.com' } },
            required: ['url']
          }
        },
        {
          name: 'open_app',
          description: "Open ANY application installed on the user's own computer, by name — not limited to a fixed list (e.g. spotify, chrome, notepad, discord, vscode, or any other installed app).",
          parameters: {
            type: 'object',
            properties: { name: { type: 'string', description: 'Name of the application to open' } },
            required: ['name']
          }
        },
        {
          name: 'scan_screen',
          description: "Take a screenshot of the user's screen right now so you can see and describe what's currently on it.",
          parameters: { type: 'object', properties: {} }
        },
        {
          name: 'get_weather',
          description: "Get the current weather at the user's location (uses their browser's location).",
          parameters: { type: 'object', properties: {} }
        },
        {
          name: 'get_system_stats',
          description: "Check the user's own computer's live battery, CPU and RAM usage.",
          parameters: { type: 'object', properties: {} }
        },
        {
          name: 'open_path',
          description: "Open a specific file or folder on the user's own computer by its path.",
          parameters: {
            type: 'object',
            properties: { path: { type: 'string', description: 'The full file or folder path to open' } },
            required: ['path']
          }
        },
        {
          name: 'make_presentation',
          description: 'Generate and download a PowerPoint presentation on a given topic.',
          parameters: {
            type: 'object',
            properties: {
              topic: { type: 'string', description: 'What the presentation should be about' },
              slide_count: { type: 'integer', description: 'How many content slides to include, default 6' }
            },
            required: ['topic']
          }
        }
      ]
    }];

    const callGemini = () => fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-goog-api-key': apiKey,
        },
        body: JSON.stringify({
          system_instruction: system ? { parts: [{ text: system }] } : undefined,
          contents: contents,
          ...(tools ? { tools, toolConfig: { includeServerSideToolInvocations: true } } : {}),
          generationConfig: {
            maxOutputTokens: json_mode ? 1400 : 900,
            ...(json_mode ? { response_mime_type: 'application/json' } : {})
          },
        }),
      }
    );

    let response = await callGemini();
    let data = await response.json();

    // If Google's servers are briefly overloaded, wait a moment and try once more
    // automatically, instead of failing right away.
    if (!response.ok && response.status === 503) {
      await new Promise(r => setTimeout(r, 1500));
      response = await callGemini();
      data = await response.json();
    }

    if (!response.ok) {
      console.error('Gemini API error:', data);
      return res.status(response.status).json({ error: data.error?.message || 'Gemini API error' });
    }

    const parts = data.candidates?.[0]?.content?.parts || [];

    // If Gemini decided to use one of the tools above, hand that decision
    // back to the frontend to actually carry out via the Jarvis Bridge.
    const fnCallPart = parts.find(p => p.functionCall);
    if (fnCallPart) {
      return res.status(200).json({
        content: [{ type: 'tool_use', name: fnCallPart.functionCall.name, input: fnCallPart.functionCall.args || {} }]
      });
    }

    const replyText = parts.map(p => p.text || '').join('');
    return res.status(200).json({ content: [{ type: 'text', text: replyText }] });
  } catch (err) {
    console.error('Server error:', err);
    return res.status(500).json({ error: 'Something went wrong on the server.' });
  }
}

