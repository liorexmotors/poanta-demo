export type FeedItem = {
  id?: string;
  headline: string;
  summary?: string;
  context?: string;
  takeaway?: string;
  category?: string;
  topic?: string;
  sourceName?: string;
  source?: string;
  sourceUrl?: string;
  imageUrl?: string;
  publishedAt?: string;
  updatedAt?: string;
};

export type FeedResponse = {
  items: FeedItem[];
  updatedAt?: string;
};
