export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

function url(path: string) {
  return `${API_URL}${path}`;
}

export const endpoints = {
  auth: {
    me: url("/api/auth/me/"),
    logout: url("/api/auth/logout/"),
    workspaces: {
      brands: url("/api/auth/workspaces/brands/"),
      agents: url("/api/auth/workspaces/agents/"),
    },
  },
  agents: {
    login: url("/api/agents/login/"),
    register: url("/api/agents/register/"),
    me: url("/api/agents/me/"),
    dashboard: url("/api/agents/dashboard/"),
    performance: url("/api/agents/performance/"),
    brands: url("/api/agents/brands/"),
    brandDetail: (id: number) => url(`/api/agents/brands/${id}/`),
    brandJoin: (id: number) => url(`/api/agents/brands/${id}/join/`),
    products: url("/api/agents/products/"),
    productDetail: (id: number) => url(`/api/agents/products/${id}/`),
    teams: url("/api/agents/teams/"),
    teamDetail: (id: number) => url(`/api/agents/teams/${id}/`),
    teamJoin: (id: number) => url(`/api/agents/teams/${id}/join/`),
    joinRequests: url("/api/agents/join-requests/"),
    joinRequestCancel: (id: number) => url(`/api/agents/join-requests/${id}/cancel/`),
    invitations: url("/api/agents/invitations/"),
    invitationAccept: (id: number) => url(`/api/agents/invitations/${id}/accept/`),
    invitationDecline: (id: number) => url(`/api/agents/invitations/${id}/decline/`),
    links: url("/api/agents/links/"),
    linkDetail: (id: number) => url(`/api/agents/links/${id}/`),
    linkShareIntent: (id: number) => url(`/api/agents/links/${id}/share-intent/`),
    events: url("/api/agents/events/"),
    wallet: url("/api/agents/wallet/"),
    earnings: url("/api/agents/earnings/"),
    payoutAccounts: url("/api/agents/payout-accounts/"),
    withdrawals: url("/api/agents/withdrawals/"),
    withdrawalCancel: (id: number) => url(`/api/agents/withdrawals/${id}/cancel/`),
  },
  brands: {
    login: url("/api/brands/login/"),
    register: url("/api/brands/register/"),
    me: url("/api/brands/me/"),
    list: url("/api/brands/"),
    detail: (id: number) => url(`/api/brands/${id}/`),
    categories: url("/api/brands/categories/"),
    products: url("/api/brands/products/"),
    productsQuery: (params: { brand?: string; category?: string } = {}) => {
      const query = new URLSearchParams();
      if (params.brand) query.set("brand", params.brand);
      if (params.category) query.set("category", params.category);
      const suffix = query.toString();
      return url(`/api/brands/products/${suffix ? `?${suffix}` : ""}`);
    },
    productDetail: (id: number) => url(`/api/brands/products/${id}/`),
    productShare: (id: number) => url(`/api/brands/products/${id}/share/`),
    shareRedirect: (code: string) => url(`/s/${code}`),
    teams: url("/api/brands/teams/"),
    teamDetail: (id: number, params: Record<string, string> = {}) => {
      const query = new URLSearchParams();
      Object.entries(params).forEach(([key, value]) => {
        if (value) query.set(key, value);
      });
      const suffix = query.toString();
      return url(`/api/brands/teams/${id}/${suffix ? `?${suffix}` : ""}`);
    },
    teamInvite: (id: number) => url(`/api/brands/teams/${id}/invite/`),
    membership: (id: number) => url(`/api/brands/memberships/${id}/`),
    invitations: url("/api/brands/invitations/"),
    invitationCancel: (id: number) => url(`/api/brands/invitations/${id}/cancel/`),
    joinRequests: url("/api/brands/join-requests/"),
    joinRequestApprove: (id: number) => url(`/api/brands/join-requests/${id}/approve/`),
    joinRequestReject: (id: number) => url(`/api/brands/join-requests/${id}/reject/`),
    agents: url("/api/brands/agents/"),
    agentSearch: (params: { q?: string; team?: string } = {}) => {
      const query = new URLSearchParams();
      if (params.q) query.set("q", params.q);
      if (params.team) query.set("team", params.team);
      const suffix = query.toString();
      return url(`/api/brands/agents/search/${suffix ? `?${suffix}` : ""}`);
    },
    campaigns: url("/api/brands/campaigns/"),
    campaignDetail: (id: number) => url(`/api/brands/campaigns/${id}/`),
    campaignPerformance: (id: number) => url(`/api/brands/campaigns/${id}/performance/`),
    performance: url("/api/brands/performance/"),
    links: url("/api/brands/links/"),
    events: url("/api/brands/events/"),
    distribution: url("/api/brands/distribution/"),
    commissionRules: url("/api/brands/commission-rules/"),
    commissionRuleDetail: (id: number) => url(`/api/brands/commission-rules/${id}/`),
    commissionPreview: url("/api/brands/commissions/preview/"),
    productCommission: (id: number) => url(`/api/brands/products/${id}/commission/`),
  },
  ai: {
    preferences: url("/api/ai/preferences/"),
    productAnalyze: url("/api/ai/product/analyze/"),
    referenceAnalyze: url("/api/ai/reference/analyze/"),
    briefGenerate: url("/api/ai/brief/generate/"),
    scriptGenerate: url("/api/ai/script/generate/"),
    transcribe: url("/api/ai/transcribe/"),
    videoGenerate: url("/api/ai/video/generate/"),
    videoDraft: url("/api/ai/video/draft/"),
    videoBrief: url("/api/ai/video/creative-brief/"),
    videoConcepts: url("/api/ai/video/concepts/"),
    videos: url("/api/ai/videos/"),
    videoFailed: url("/api/ai/videos/failed/"),
    videoDetail: (id: number) => url(`/api/ai/video/${id}/`),
    videoStatus: (id: number) => url(`/api/ai/video/${id}/status/`),
    videoCancel: (id: number) => url(`/api/ai/video/${id}/cancel/`),
    videoProjectConcepts: (id: number) => url(`/api/ai/video/${id}/concepts/`),
    videoSelectConcept: (id: number) => url(`/api/ai/video/${id}/select-concept/`),
    videoTimeline: (id: number) => url(`/api/ai/video/${id}/timeline/`),
    videoProjectGenerate: (id: number) => url(`/api/ai/video/${id}/generate/`),
    videoBulkGenerate: (id: number) => url(`/api/ai/video/${id}/bulk-generate/`),
    videoAmendments: (id: number) => url(`/api/ai/video/${id}/amendments/`),
    videoApproveScenes: (id: number) => url(`/api/ai/video/${id}/approve-scenes/`),
    videoCorrect: (id: number) => url(`/api/ai/video/${id}/correct/`),
    videoRegenerate: (id: number) => url(`/api/ai/video/${id}/regenerate/`),
    videoQa: (id: number) => url(`/api/ai/video/${id}/qa/`),
    videoApprove: (id: number) => url(`/api/ai/video/${id}/approve/`),
    videoExport: (id: number) => url(`/api/ai/video/${id}/export/`),
    videoPublish: (id: number) => url(`/api/ai/video/${id}/publish/`),
    videoScene: (id: number) => url(`/api/ai/video/scenes/${id}/`),
    videoSceneDuplicate: (id: number) => url(`/api/ai/video/scenes/${id}/duplicate/`),
    videoSceneRegenerate: (id: number) => url(`/api/ai/video/scenes/${id}/regenerate/`),
    videoSaveStyle: (id: number) => url(`/api/ai/video/${id}/save-style/`),
    voices: url("/api/ai/voices/"),
    characters: url("/api/ai/characters/"),
    charactersQuery: (archived = false) => url(`/api/ai/characters/${archived ? "?archived=1" : ""}`),
    characterDetail: (id: number) => url(`/api/ai/characters/${id}/`),
    characterArchive: (id: number) => url(`/api/ai/characters/${id}/archive/`),
    characterRestore: (id: number) => url(`/api/ai/characters/${id}/restore/`),
    characterDuplicate: (id: number) => url(`/api/ai/characters/${id}/duplicate/`),
    characterVideos: (id: number) => url(`/api/ai/characters/${id}/videos/`),
    characterMasterReference: (id: number) => url(`/api/ai/characters/${id}/master-reference/`),
    characterMasterApprove: (id: number) => url(`/api/ai/characters/${id}/master-reference/approve/`),
    characterFromPresenter: url("/api/ai/characters/from-presenter/"),
    styles: url("/api/ai/styles/"),
    styleDetail: (id: number) => url(`/api/ai/styles/${id}/`),
    styleApply: (id: number) => url(`/api/ai/styles/${id}/apply/`),
    styleBulk: (id: number) => url(`/api/ai/styles/${id}/bulk/`),
    usage: url("/api/ai/usage/"),
    bulkVideos: url("/api/ai/bulk-video/"),
    bulkVideoDetail: (id: number) => url(`/api/ai/bulk-video/${id}/`),
    bulkVideoAnalyze: (id: number) => url(`/api/ai/bulk-video/${id}/analyze-reference/`),
    bulkVideoPlan: (id: number) => url(`/api/ai/bulk-video/${id}/generate-plan/`),
    bulkVideoPatchPlan: (id: number) => url(`/api/ai/bulk-video/${id}/plan/`),
    bulkVideoGenerate: (id: number) => url(`/api/ai/bulk-video/${id}/generate/`),
    bulkVideoRetry: (id: number) => url(`/api/ai/bulk-video/${id}/retry-failed/`),
    bulkVideoCancel: (id: number) => url(`/api/ai/bulk-video/${id}/cancel/`),
    bulkVideoStatus: (id: number) => url(`/api/ai/bulk-video/${id}/status/`),
  },
  commerce: {
    conversions: url("/api/commerce/conversions/"),
    analytics: url("/api/commerce/analytics/"),
    shareConfirmed: url("/api/commerce/share-confirmed/"),
  },
} as const;

export type Role = "agent" | "producer";

export type ActingAccount = {
  type: Role;
  userId: number;
  brandId?: number | null;
  name: string;
  subtitle?: string;
  email?: string;
  username?: string;
  mobile?: string;
  location?: string;
};

export type Account = {
  id: number;
  username: string;
  name: string;
  email: string;
  mobile: string;
  location: string;
  role: Role;
  is_superuser?: boolean;
};

export type Category = {
  id: number;
  name: string;
  slug: string;
};

export type Brand = {
  id: number;
  category: number;
  category_name: string;
  name: string;
  website: string;
  description: string;
  location: string;
  created_at: string;
};

export type BrandOwnerProfile = {
  id: number;
  username: string;
  name: string;
  email: string;
  mobile: string;
  location: string;
  role: Role;
  company: Brand | null;
  brands: Brand[];
};

export type ProfileUpdatePayload = {
  name: string;
  username: string;
  email: string;
  mobile: string;
  location: string;
  company?: {
    name: string;
    website: string;
    description: string;
    location: string;
    category: number;
  };
  current_password?: string;
  password?: string;
  password_confirm?: string;
};

export type ProductImage = {
  id: number;
  url: string;
};

export type Product = {
  id: number;
  brand: number;
  brand_name: string;
  category: number;
  category_name: string;
  name: string;
  description: string;
  product_url: string;
  price: string;
  commission: string;
  commission_amount: string;
  variants: string[];
  dimensions: string;
  materials: string;
  offer: string;
  offer_expiry: string | null;
  approved_claims: string[];
  prohibited_claims: string[];
  certifications: string[];
  evidence: string[];
  shipping_conditions: string;
  known_mistakes: string[];
  prohibited_representations: string[];
  images: ProductImage[];
  demo_videos: ProductImage[];
  share_count: number;
  open_count: number;
  created_at: string;
};

export type AgentProfile = {
  id: number;
  bio: string;
  status: string;
  created_at: string;
  updated_at: string;
  user: Account;
};

export type AgentBrandCard = {
  id: number;
  name: string;
  description: string;
  location: string;
  website: string;
  category: number;
  category_name: string;
  status: string;
  product_count: number;
  team_count: number;
  membership_status: string;
};

export type AgentCampaign = {
  id: number;
  name: string;
  status: string;
  product_id: number | null;
  team_id: number | null;
};

export type AgentTeam = {
  id: number;
  name: string;
  description: string;
  status: string;
  brand_id: number;
  brand_name: string;
  membership_status: string;
  join_request_status: string;
  invitation_status: string;
  join_request_id: number | null;
  invitation_id: number | null;
  can_join: boolean;
  can_cancel_request: boolean;
  can_accept_invitation: boolean;
  member_count: number;
  campaigns: AgentCampaign[];
  created_at: string;
};

export type AgentProductCard = {
  id: number;
  name: string;
  description: string;
  price: string;
  brand_id: number;
  brand_name: string;
  category_name: string;
  images: ProductImage[];
  can_share: boolean;
  created_at: string;
};

export type AgentCommission = {
  source: string;
  rate_type: string;
  rate_value: string;
  gross: string;
  platform_fee_percent: string;
  platform_fee: string;
  net: string;
  team_id: number;
  team_name: string;
  team_specific: boolean;
};

export type AgentContent = {
  id: number;
  status: string;
  duration_seconds: number;
  language: string;
  preview_url: string;
  final_url: string;
  export_url: string;
  updated_at: string;
};

export type AgentProductDetail = AgentProductCard & {
  demo_videos: ProductImage[];
  content: AgentContent[];
  commissions: AgentCommission[];
  teams: { id: number; name: string }[];
  approved_claims: string[];
  offer: string;
  offer_expiry: string | null;
  product_url: string;
  materials: string;
  variants: string[];
  commission: string;
  commission_amount: string;
};

export type AgentBrandDetail = {
  brand: AgentBrandCard;
  teams: AgentTeam[];
  products: AgentProductCard[];
};

export type AgentTrackingEvent = {
  id: number;
  event_type: string;
  label: string;
  link_code: string;
  created_at: string;
  metadata: Record<string, unknown>;
};

export type AgentTrackingLink = {
  id: number;
  code: string;
  url: string;
  status: string;
  product_id: number;
  product_name: string;
  brand_id: number;
  brand_name: string;
  team_id: number;
  team_name: string;
  campaign_id: number | null;
  campaign_name: string;
  content_id: number | null;
  clicks: number;
  opens: number;
  unique_opens: number;
  conversions: number;
  share_intents: number;
  share_confirmed?: number;
  earnings_gross: string;
  earnings_fee: string;
  earnings_net: string;
  commission: AgentCommission | null;
  created_at: string;
  activity?: AgentTrackingEvent[];
};

export type AgentDashboard = {
  total_clicks: number;
  total_opens: number;
  unique_opens: number;
  total_conversions: number;
  gross_commission: string;
  platform_fees: string;
  net_earnings: string;
  available_balance: string;
  pending_balance: string;
  paid_balance: string;
  currency: string;
  recent_activity: AgentTrackingEvent[];
  top_products: {
    id: number;
    name: string;
    brand_name: string;
    opens: number;
    conversions: number;
  }[];
  active_teams: {
    id: number;
    name: string;
    brand_id: number;
    brand_name: string;
    status: string;
  }[];
};

export type AgentPerformance = {
  links: number;
  opens: number;
  unique_opens: number;
  clicks: number;
  conversions: number;
  share_intents: number;
  share_confirmed?: number;
  gross_commission: string;
  platform_fees: string;
  net_commission: string;
};

export type AgentCommissionTransaction = {
  id: number;
  status: string;
  currency: string;
  gross_amount: string;
  platform_fee_percent: string;
  platform_fee_amount: string;
  agent_net_amount: string;
  rate_type: string;
  rate_value: string;
  product_name: string;
  brand_name: string;
  team_name: string;
  tracking_code: string;
  created_at: string;
};

export type AgentWallet = {
  currency: string;
  pending_balance: string;
  available_balance: string;
  withdrawn_balance?: string;
  paid_balance: string;
  updated_at: string;
};

export type AgentEarnings = AgentWallet & {
  pending: AgentCommissionTransaction[];
  available: AgentCommissionTransaction[];
  paid: AgentCommissionTransaction[];
  transactions: AgentCommissionTransaction[];
};

export type AgentPayoutAccount = {
  id: number;
  label: string;
  destination_ref: string;
  is_default: boolean;
  created_at: string;
};

export type AgentWithdrawal = {
  id: number;
  amount: string;
  currency: string;
  status: string;
  destination_ref: string;
  payout_account: number | null;
  payout_account_label: string;
  rejection_reason: string;
  requested_at: string;
  reviewed_at: string | null;
  processed_at: string | null;
};

export type AgentWithdrawalsPayload = AgentWallet & {
  withdrawals: AgentWithdrawal[];
};

export type AgentJoinRequest = {
  id: number;
  team_id: number;
  team_name: string;
  brand_id: number;
  brand_name: string;
  status: string;
  message: string;
  can_cancel: boolean;
  created_at: string;
  responded_at: string | null;
};

export type AgentInvitation = {
  id: number;
  team_id: number;
  team_name: string;
  brand_id: number;
  brand_name: string;
  status: string;
  created_at: string;
  expires_at: string | null;
  responded_at: string | null;
  can_accept: boolean;
  can_decline: boolean;
};

export type BrandTeam = {
  id: number;
  name: string;
  description: string;
  status: string;
  brand_id: number;
  brand_name: string;
  member_count: number;
  pending_requests: number;
  pending_invites: number;
  created_at: string;
  updated_at: string;
};

export type BrandCommissionLayer = {
  label: string;
  configured: boolean;
  effective: boolean;
  source: string;
  rate_type: string;
  rate_value: string | null;
  gross: string | null;
  platform_fee: string | null;
  net: string | null;
  rule_id: number | null;
};

export type BrandCommissionPreview = {
  currency: string;
  platform_fee_percent: string;
  layers: {
    default: BrandCommissionLayer;
    team: BrandCommissionLayer;
    agent: BrandCommissionLayer;
    campaign: BrandCommissionLayer;
  };
  effective: {
    layer: string;
    source: string;
    rate_type: string;
    rate_value: string;
    gross: string;
    platform_fee_percent: string;
    platform_fee: string;
    net: string;
    rule_id: number | null;
  } | null;
  precedence: string[];
};

export type BrandTeamMember = {
  id: number;
  agent_id: number;
  agent_name: string;
  agent_username: string;
  agent_email: string;
  status: string;
  joined_at: string;
  links: number;
  opens: number;
  unique_opens?: number;
  clicks: number;
  conversions: number;
  gross_commission: string;
  misa_fee: string;
  agent_net_earnings: string;
  commission_override_type: string;
  commission_override_value: string | null;
  effective_commission?: BrandCommissionPreview["effective"];
  commission_layers?: BrandCommissionPreview["layers"];
};

export type BrandInvitation = {
  id: number;
  team_id: number;
  team_name: string;
  brand_id: number;
  brand_name: string;
  agent_id: number;
  agent_name: string;
  agent_username: string;
  agent_email: string;
  status: string;
  invited_by_name: string;
  created_at: string;
  expires_at: string | null;
  responded_at: string | null;
  can_cancel: boolean;
};

export type BrandJoinRequest = {
  id: number;
  team_id: number;
  team_name: string;
  brand_id: number;
  brand_name: string;
  agent_id: number;
  agent_name: string;
  agent_username: string;
  agent_email: string;
  status: string;
  message: string;
  created_at: string;
  responded_at: string | null;
  can_review: boolean;
};

export type BrandTeamDetail = {
  team: BrandTeam;
  members: BrandTeamMember[];
  invitations: BrandInvitation[];
  join_requests: BrandJoinRequest[];
};

export type BrandAgentSearchResult = {
  id: number;
  username: string;
  name: string;
  email: string;
  location: string;
  status: string;
};

export type BrandAgentRow = {
  id: number;
  agent_id: number;
  agent_name: string;
  agent_username: string;
  agent_email: string;
  status: string;
  team_id: number;
  team_name: string;
  brand_id: number;
  brand_name: string;
  joined_at: string;
};

export type BrandContentRef = {
  id: number;
  status: string;
  duration_seconds: number;
  language: string;
  preview_url: string;
  final_url: string;
  export_url: string;
  updated_at: string;
  available: boolean;
};

export type BrandCampaign = {
  id: number;
  name: string;
  description: string;
  status: string;
  brand: number;
  brand_id: number;
  brand_name: string;
  product: number | null;
  product_id: number | null;
  product_name: string | null;
  team: number | null;
  team_id: number | null;
  team_name: string | null;
  content: number | null;
  content_id: number | null;
  content_status: string;
  start_at: string | null;
  end_at: string | null;
  commission_type: string;
  commission_value: string | null;
  created_at: string;
  updated_at: string;
  performance?: BrandPerformance;
  content_ref?: BrandContentRef;
};

export type BrandPerformance = {
  total_agents: number;
  active_agents: number;
  links: number;
  opens: number;
  unique_opens?: number;
  clicks: number;
  conversions: number;
  share_intents: number;
  gross_commissions: string;
  platform_fees: string;
  agent_payouts: string;
  by_product?: {
    id: number;
    name: string;
    opens: number;
    unique_opens?: number;
    clicks: number;
    conversions: number;
  }[];
};

export type BrandDistributionRow = {
  product_id: number;
  product_name: string;
  brand_id: number;
  brand_name: string;
  generated_content: number;
  available_videos: number;
  content: BrandContentRef[];
  available_content: BrandContentRef[];
  active_agents: number;
  tracking_links: number;
  opens: number;
  unique_opens?: number;
  clicks: number;
  conversions: number;
  commission_generated: string;
};

export type BrandCommissionRule = {
  id: number;
  name: string;
  scope: string;
  brand: number | null;
  brand_name: string;
  product: number | null;
  product_name: string;
  team: number | null;
  team_name: string;
  agent: number | null;
  agent_name: string;
  rate_type: string;
  rate_value: string;
  currency: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type BrandPerformanceFilters = {
  date_from?: string;
  date_to?: string;
  team?: string;
  agent?: string;
  product?: string;
  campaign?: string;
};

export type AgentLinkFilters = {
  product?: string;
  brand?: string;
  team?: string;
  campaign?: string;
  status?: string;
  date_from?: string;
  date_to?: string;
};

export type StudioLanguage =
  | "conversational_bm"
  | "formal_bm"
  | "bm_english"
  | "english"
  | "chinese"
  | "cantonese"
  | "hokkien"
  | "mandarin_my"
  | "tamil_my";

export type StudioStyle = "warm" | "bold" | "calm" | "luxury";

export type QaStatus = "passed" | "warning" | "failed" | "";

export type QaResultCheck = {
  name: string;
  status: QaStatus | "skipped" | "not_checked";
  detail: string;
  qa_category?: string;
  source?: string;
  confidence?: number;
  severity?: string;
  scene_id?: string;
  affected_scenes?: string[];
  timestamp?: number;
  start?: number;
  end?: number;
  frame_url?: string;
  recommended_action?: string;
  evidence?: string;
  checked?: boolean;
  verified?: boolean;
  locked?: boolean;
};

export type QaIssue = {
  type?: string;
  severity?: string;
  confidence?: number;
  start?: number;
  end?: number;
  timestamp?: number;
  scene_id?: string;
  message?: string;
  recommended_action?: string;
  affected_scenes?: string[];
  frame_url?: string;
  source?: string;
  qa_category?: string;
};

export type SceneQaGate = {
  scene_id?: number;
  scene_key: string;
  order?: number;
  label?: string;
  identity?: {
    status?: string;
    required?: boolean;
    confidence?: number | null;
    threshold?: number;
    comparison_performed?: boolean;
    face_detected?: boolean;
    reason?: string;
    reference_url?: string;
    generated_face_url?: string;
    character_name?: string;
    reference_character_id?: number | null;
    reference_image_id?: number | null;
  };
  audio?: {
    status?: string;
    required?: boolean;
    has_audio_stream?: boolean;
    speech_detected?: boolean;
    duration_seconds?: number | null;
    reason?: string;
  };
};

export type QaLayer = {
  structural?: { status?: string; detail?: string };
  visual?: { status?: string; confidence?: number; source?: string; detail?: string };
};

export type StudioScene = {
  id: number;
  scene_key: string;
  order: number;
  title: string;
  visual: string;
  narration: string;
  caption: string;
  duration: number;
  image_url: string;
  video_url: string;
  audio_url: string;
  start_time?: number;
  end_time?: number;
  shot_description?: string;
  presenter_action?: string;
  camera_framing?: string;
  camera_movement?: string;
  lighting?: string;
  pace?: string;
  transition?: string;
  voice_over?: string;
  on_screen_caption?: string;
  benefit?: string;
  approved_claim?: string;
  location?: string;
  background?: string;
  sound_direction?: string;
  composition?: string;
  depth_of_field?: string;
  lens?: string;
  product_locked?: boolean;
  presenter_locked?: boolean;
  location_locked?: boolean;
  script_locked?: boolean;
  caption_locked?: boolean;
  scene_locked?: boolean;
  scene_status?: string;
  generation_id?: string;
  qa_status?: QaStatus;
  qa_results?: unknown[];
  approved?: boolean;
  error?: string;
  generation_status?: string;
  failure_code?: string;
  failure_message?: string;
  provider?: string;
  provider_request_id?: string;
  retry_count?: number;
  pipeline_error?: {
    stage?: string;
    scene?: string;
    provider?: string;
    error_type?: string;
    task_id?: string;
    retry_count?: number;
    detail?: string;
    code?: string;
    status?: number;
    retryable?: boolean;
  };
};

export type CreativeConcept = {
  id: string;
  title: string;
  style: string;
  strategy: string;
  audience_angle?: string;
  hook: string;
  narrative: string;
  cta: string;
  estimated_duration?: number;
  why_it_works?: string;
  template_id?: string;
  scenes: Partial<StudioScene>[];
};

export type AmendmentRecommendation = {
  id: string;
  type: string;
  detected_problem: string;
  severity: string;
  start?: number;
  end?: number;
  affected_scenes?: string[];
  suggested_amendment: string;
  proposed_correction?: string;
  expected_benefit: string;
  needs_regeneration?: boolean;
  reason?: string;
  issue?: string;
  timestamp?: number;
  stage?: string;
  selected?: boolean;
  editable_text?: string;
  confidence?: number;
  frame_url?: string;
  source?: string;
  scene_id?: string;
};

export type VideoProject = {
  id: number;
  product: number;
  product_name: string;
  product_snapshot: Record<string, unknown>;
  language: StudioLanguage;
  speaking_style: StudioStyle;
  speaker_gender?: "female" | "male" | "neutral";
  character_config?: {
    character: number | null;
    character_name: string;
    language: string;
    tone: string;
    gender: string;
    voice_provider: string;
    voice_id: string;
    voice_name: string;
    appearance_snapshot: string;
    identity_snapshot: Record<string, unknown>;
    reference_snapshot: { view_type?: string; storage_name?: string }[];
  } | null;
  duration_seconds: number;
  reference_url: string;
  reference_video_url?: string;
  merchant_instructions: string;
  kalodata_insights?: {
    available?: boolean;
    category_scripts?: unknown[];
    winning_structures?: unknown[];
    shot_plans?: unknown[];
    customer_objections?: unknown[];
    content_ideas?: unknown[];
  };
  creative_directions?: CreativeConcept[];
  selected_concept_id?: string;
  amendment_recommendations?: AmendmentRecommendation[];
  amendment_history?: Record<string, unknown>[];
  director_events?: { type?: string; at?: string; payload?: Record<string, unknown> }[];
  tiktok_checks?: {
    status?: QaStatus;
    disclaimer?: string;
    checks?: { name: string; status: QaStatus; detail: string }[];
  };
  provider_request_id?: string;
  product_analysis: Record<string, unknown>;
  reference_analysis: Record<string, unknown>;
  creative_brief: Record<string, unknown>;
  script: Record<string, unknown>;
  shot_plan: Record<string, unknown>;
  narration: Record<string, unknown>;
  captions: Record<string, unknown>;
  qa_results: {
    status?: QaStatus;
    summary?: string;
    checks?: QaResultCheck[];
    unsupported_claims?: string[];
    disclaimer?: string;
    issues?: QaIssue[];
    layers?: Record<string, QaLayer>;
    serious_issues?: QaResultCheck[];
    release_blocking?: QaResultCheck[];
    scene_gates?: SceneQaGate[];
    scene_gates_passed?: boolean;
  };
  qa_status: QaStatus;
  status: string;
  stage_label: string;
  progress: number;
  generation_metrics?: {
    project_creation_ms?: number;
    script_generation_ms?: number;
    storyboard_generation_ms?: number;
    scene_generation_ms?: number;
    scene_generation_total_ms?: number;
    scene_generation_parallel_ms?: number;
    scene_concurrency?: number;
    scene_count?: number;
    assembly_ms?: number;
    qa_ms?: number;
    total_generation_ms?: number;
    project_creation_started_ms?: number;
    script_generation_started_ms?: number;
    scenes?: {
      scene_id?: number;
      scene_key?: string;
      duration_ms?: number;
      status?: string;
      provider?: string;
      model?: string;
    }[];
    started_at?: string;
    completed_at?: string;
  };
  error_message: string;
  error_type?: string;
  version: number;
  scenes?: StudioScene[];
  preview_url: string;
  final_url: string;
  export_url: string;
  poster_url?: string;
  approved_at: string | null;
  created_at?: string;
  updated_at?: string;
};

export type VoiceOption = {
  provider: string;
  voice_id: string;
  voice_name: string;
  gender: string;
  language: string;
  language_code: string;
};

export type CharacterReference = {
  id: number;
  url: string;
  view_type: string;
  sort_order: number;
  created_at?: string;
};

export type CharacterMasterVersion = {
  id: number;
  version: number;
  url: string;
  source_url: string;
  created_at?: string;
  approved_at?: string | null;
};

export type StudioCharacter = {
  id: number;
  brand: number;
  brand_name: string;
  name: string;
  description: string;
  gender: "female" | "male" | "neutral";
  appearance_description: string;
  personality_description: string;
  wardrobe_description: string;
  default_language: string;
  default_tone: string;
  default_voice_provider: string;
  default_voice_id: string;
  default_voice_name: string;
  status: "active" | "archived";
  references: CharacterReference[];
  preview_url: string;
  source_front_url?: string;
  front_source_available?: boolean;
  master_reference_url?: string;
  master_reference_status?: "pending" | "processing" | "ready" | "failed";
  master_reference_version?: number;
  master_reference_prompt?: string;
  master_reference_created_at?: string | null;
  master_reference_approved?: boolean;
  latest_master_url?: string;
  latest_master_version?: number;
  latest_master?: CharacterMasterVersion | null;
  video_count: number;
  created_at: string;
  updated_at: string;
};

export type StyleRecipe = {
  id: number;
  key: string;
  name: string;
  recipe: Record<string, unknown>;
  source_project?: number | null;
  source_project_id?: number | null;
  source_qa_status?: string;
  product_name?: string;
  created_at?: string;
  updated_at?: string;
};

export type UsageRecord = {
  id: number;
  provider: string;
  operation: string;
  status: string;
  cost_amount: string;
  created_at: string;
  project: number | null;
};

export type BulkStudioMode =
  | "character"
  | "product"
  | "existing_video"
  | "reference_location"
  | "reference_character";

export type BulkGenerationStatus =
  | "draft"
  | "analyzing"
  | "plan_ready"
  | "queued"
  | "generating"
  | "completed"
  | "completed_with_errors"
  | "failed"
  | "cancelled";

export type BulkItemStatus = "draft" | "planned" | "queued" | "generating" | "completed" | "failed" | "cancelled";

export type BulkVariation = {
  sequence?: number;
  title?: string;
  location?: string;
  hook?: string;
  story?: string;
  action?: string;
  camera?: string;
  environment?: string;
  character_id?: number;
  locked_elements?: string[];
  variable_elements?: string[];
};

export type BulkGenerationItem = {
  id: number;
  sequence: number;
  title: string;
  variation_config: BulkVariation;
  video_project: {
    id: number;
    status: string;
    progress: number;
    stage_label: string;
    error_message: string;
    preview_url: string;
    poster_url?: string;
    product_name: string;
    generation_metrics?: VideoProject["generation_metrics"];
    created_at?: string;
    updated_at?: string;
  } | null;
  status: BulkItemStatus;
  error_message: string;
  created_at?: string;
  completed_at?: string | null;
};

export type BulkGeneration = {
  id: number;
  mode: BulkStudioMode;
  title: string;
  product: number;
  product_name: string;
  character: number | null;
  character_name: string;
  character_ids: number[];
  language: string;
  speaking_style: string;
  duration_seconds: number;
  requested_count: number;
  locks: Record<string, boolean>;
  variables: Record<string, boolean>;
  instruction: string;
  reference_url: string;
  reference_video_url: string;
  master_spec: Record<string, unknown>;
  generation_plan: BulkVariation[];
  status: BulkGenerationStatus;
  error_message: string;
  completed_count: number;
  failed_count: number;
  generating_count: number;
  items: BulkGenerationItem[];
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  updated_at: string;
};

export type VideoStatus = {
  id: number;
  status: string;
  stage_label: string;
  progress: number;
  error_message: string;
  error_type?: string;
  qa_status: QaStatus;
  version: number;
  updated_at?: string;
  preview_url?: string;
  final_url?: string;
  export_url?: string;
  generation_metrics?: VideoProject["generation_metrics"];
  scene_statuses?: {
    id: number;
    scene_key: string;
    order: number;
    title: string;
    status: string;
    error: string;
    pipeline_error?: Record<string, unknown>;
  }[];
};

export type ProductShare = {
  code: string;
  url: string;
  share_count: number;
  open_count: number;
};

export type AuthResponse = {
  token: string;
  user: Account;
};

export type AgentRegisterPayload = {
  username: string;
  name: string;
  email: string;
  mobile: string;
  location: string;
  password: string;
  password_confirm: string;
};

export type BrandRegisterPayload = AgentRegisterPayload & {
  company_name: string;
  company_website: string;
  company_description: string;
};

export type ApiError = {
  detail?: string;
  [key: string]: unknown;
};

export type WorkspaceBrand = {
  id: number;
  name: string;
  location: string;
  category_name: string;
  owner_id: number;
  owner_name: string;
  owner_email: string;
  owner_username: string;
};

export type WorkspaceAgent = {
  id: number;
  name: string;
  username: string;
  email: string;
  mobile: string;
  location: string;
};

export function flattenErrors(payload: ApiError): string {
  if (typeof payload.detail === "string") {
    return payload.detail;
  }

  const messages: string[] = [];
  for (const [field, value] of Object.entries(payload)) {
    if (field === "detail") continue;
    if (Array.isArray(value)) {
      messages.push(value.map(String).join(" "));
    } else if (typeof value === "string") {
      messages.push(value);
    }
  }
  return messages.join(" ") || "Something went wrong. Please try again.";
}

export const ACTING_STORAGE_KEY = "dckbrand.acting";

function readActingHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(ACTING_STORAGE_KEY);
    if (!raw) return {};
    const acting = JSON.parse(raw) as { userId?: number; brandId?: number | null };
    const headers: Record<string, string> = {};
    if (acting.userId) headers["X-Acting-User"] = String(acting.userId);
    if (acting.brandId) headers["X-Acting-Brand"] = String(acting.brandId);
    return headers;
  } catch {
    return {};
  }
}

export async function api<T>(
  url: string,
  options: RequestInit & { token?: string | null } = {},
): Promise<T> {
  const { token, headers, body, ...rest } = options;
  const isFormData = typeof FormData !== "undefined" && body instanceof FormData;
  const skipActing =
    url.includes("/api/auth/me/") ||
    url.includes("/api/auth/logout/") ||
    url.includes("/api/auth/workspaces/");
  const actingHeaders = skipActing ? {} : readActingHeaders();
  const response = await fetch(url, {
    ...rest,
    body,
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Token ${token}` } : {}),
      ...actingHeaders,
      ...headers,
    },
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const data = (await response.json().catch(() => ({}))) as ApiError;
  if (!response.ok) {
    const message = flattenErrors(data);
    if (message === "Something went wrong. Please try again." && !Object.keys(data).length) {
      throw new Error(
        response.status === 404
          ? "This action is not available on the server yet. Reload the page and try again."
          : `Request failed (${response.status}). Please try again.`,
      );
    }
    throw new Error(message);
  }
  return data as T;
}
