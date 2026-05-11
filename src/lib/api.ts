export type Fetcher = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export type RuntimeStatus = {
  status: string;
  state: string;
  mode: string;
  profile: string;
  quiet_mode: boolean;
  quality_fallback: boolean;
  last_error: string | null;
};

export type DependencyStatus = {
  name: string;
  available: boolean;
  required: boolean;
  install_hint: string;
};

export type Settings = {
  hotkeys: {
    dictation: string | string[];
    command_mode: string | string[];
  };
  models: {
    whisper: string;
    whisper_cpu_threads: number;
  };
  runtime: {
    profile: string;
    language: string;
    quiet_mode: boolean;
    quality_fallback: boolean;
    system_audio_ducking: boolean;
    system_audio_duck_volume: number;
    use_ollama: boolean;
  };
  [key: string]: unknown;
};

export type VocabularyTerm = {
  word: string;
  frequency: number;
};

export type CorrectionPair = {
  original: string;
  corrected: string;
  count: number;
};

export type SnippetRecord = {
  trigger_phrase: string;
  expansion: string;
};

export type PendingCorrection = {
  id: string;
  original: string;
  raw_transcript: string;
  app_name: string | null;
  window_title: string | null;
  detected_at: string;
};

export type LearningSuggestion =
  | { kind: "vocabulary"; phrase: string; count: number }
  | { kind: "snippet"; expansion: string; count: number };

export class RuntimeApiClient {
  constructor(
    private readonly baseUrl = "http://127.0.0.1:8765",
    private readonly fetcher: Fetcher = globalThis.fetch.bind(globalThis)
  ) {}

  getStatus(): Promise<RuntimeStatus> {
    return this.request<RuntimeStatus>("/status");
  }

  async startRuntime(mode: "dictation" | "command", language?: string): Promise<RuntimeStatus> {
    return this.request<RuntimeStatus>("/runtime/start", {
      method: "POST",
      body: JSON.stringify({ mode, language })
    });
  }

  async stopRuntime(language?: string): Promise<RuntimeStatus & { result?: unknown }> {
    return this.request<RuntimeStatus & { result?: unknown }>("/runtime/stop", {
      method: "POST",
      body: JSON.stringify({ language })
    });
  }

  async cancelRuntime(): Promise<RuntimeStatus> {
    return this.request<RuntimeStatus>("/runtime/cancel", { method: "POST" });
  }

  async warmRuntime(): Promise<void> {
    await this.request<{ status: string }>("/runtime/warmup", { method: "POST" });
  }

  async getSettings(): Promise<Settings> {
    const payload = await this.request<{ settings: Settings }>("/settings");
    return payload.settings;
  }

  async saveSettings(settings: Settings): Promise<Settings> {
    const payload = await this.request<{ settings: Settings }>("/settings", {
      method: "PUT",
      body: JSON.stringify({ settings })
    });
    return payload.settings;
  }

  async getDiagnostics(): Promise<string[]> {
    const payload = await this.request<{ lines: string[] }>("/runtime/diagnostics");
    return payload.lines;
  }

  async checkRuntime(): Promise<DependencyStatus[]> {
    const payload = await this.request<{ dependencies: DependencyStatus[] }>("/runtime/check");
    return payload.dependencies;
  }

  async listVocabulary(): Promise<VocabularyTerm[]> {
    const payload = await this.request<{ terms: VocabularyTerm[] }>("/vocabulary/terms");
    return payload.terms;
  }

  async addVocabulary(word: string): Promise<VocabularyTerm[]> {
    const payload = await this.request<{ terms: VocabularyTerm[] }>("/vocabulary/terms", {
      method: "POST",
      body: JSON.stringify({ word })
    });
    return payload.terms;
  }

  async deleteVocabulary(word: string): Promise<VocabularyTerm[]> {
    const payload = await this.request<{ terms: VocabularyTerm[] }>(
      `/vocabulary/terms/${encodeURIComponent(word)}`,
      { method: "DELETE" }
    );
    return payload.terms;
  }

  async listCorrections(): Promise<CorrectionPair[]> {
    const payload = await this.request<{ corrections: CorrectionPair[] }>(
      "/vocabulary/corrections"
    );
    return payload.corrections;
  }

  async addCorrection(original: string, corrected: string): Promise<CorrectionPair[]> {
    const payload = await this.request<{ corrections: CorrectionPair[] }>(
      "/vocabulary/corrections",
      {
        method: "POST",
        body: JSON.stringify({ original, corrected })
      }
    );
    return payload.corrections;
  }

  async deleteCorrection(original: string, corrected: string): Promise<CorrectionPair[]> {
    const params = new URLSearchParams({ original, corrected });
    const payload = await this.request<{ corrections: CorrectionPair[] }>(
      `/vocabulary/corrections?${params}`,
      { method: "DELETE" }
    );
    return payload.corrections;
  }

  async getPendingCorrections(): Promise<PendingCorrection[]> {
    const payload = await this.request<{ pending: PendingCorrection[] }>("/corrections/pending");
    return payload.pending;
  }

  async confirmPendingCorrection(
    id: string,
    original: string,
    corrected: string
  ): Promise<CorrectionPair[]> {
    const payload = await this.request<{ corrections: CorrectionPair[] }>(
      `/corrections/pending/${encodeURIComponent(id)}/confirm`,
      {
        method: "POST",
        body: JSON.stringify({ original, corrected })
      }
    );
    return payload.corrections;
  }

  async dismissPendingCorrection(id: string): Promise<void> {
    await this.request<{ status: string }>(
      `/corrections/pending/${encodeURIComponent(id)}/dismiss`,
      { method: "POST" }
    );
  }

  async getLearningSuggestions(): Promise<LearningSuggestion[]> {
    const payload = await this.request<{ suggestions: LearningSuggestion[] }>(
      "/learning/suggestions"
    );
    return payload.suggestions;
  }

  async listSnippets(): Promise<SnippetRecord[]> {
    const payload = await this.request<{ snippets: SnippetRecord[] }>("/snippets");
    return payload.snippets;
  }

  async saveSnippet(trigger_phrase: string, expansion: string): Promise<SnippetRecord[]> {
    const payload = await this.request<{ snippets: SnippetRecord[] }>("/snippets", {
      method: "POST",
      body: JSON.stringify({ trigger_phrase, expansion })
    });
    return payload.snippets;
  }

  async deleteSnippet(triggerPhrase: string): Promise<SnippetRecord[]> {
    const payload = await this.request<{ snippets: SnippetRecord[] }>(
      `/snippets/${encodeURIComponent(triggerPhrase)}`,
      { method: "DELETE" }
    );
    return payload.snippets;
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await this.fetcher(`${this.baseUrl}${path}`, {
      headers: {
        "Content-Type": "application/json",
        ...(init.headers ?? {})
      },
      ...init
    });
    if (!response.ok) {
      throw new Error(`Runtime API request failed: ${response.status}`);
    }
    return (await response.json()) as T;
  }
}
