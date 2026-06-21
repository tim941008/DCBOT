create table if not exists tracking_list (
  user_id text not null,
  course_no text not null,
  course_name text not null,
  threshold integer not null default 1,
  notify_enabled boolean not null default true,
  notify_channel_id text,
  auto_remove boolean not null default false,
  note text not null default '',
  is_wishlist boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint tracking_list_user_course_unique unique (user_id, course_no)
);

alter table tracking_list
  add column if not exists threshold integer not null default 1;

alter table tracking_list
  add column if not exists notify_enabled boolean not null default true;

alter table tracking_list
  add column if not exists notify_channel_id text;

alter table tracking_list
  add column if not exists auto_remove boolean not null default false;

alter table tracking_list
  add column if not exists note text not null default '';

alter table tracking_list
  add column if not exists is_wishlist boolean not null default false;

alter table tracking_list
  add column if not exists created_at timestamptz not null default now();

alter table tracking_list
  add column if not exists updated_at timestamptz not null default now();

create unique index if not exists tracking_list_user_course_idx
  on tracking_list (user_id, course_no);
