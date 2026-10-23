--
-- PostgreSQL database dump
--

\restrict Sb0SmDoFoX44NpJD1RpfOWuQiJitIRUE7ffYHm8vSo38m5qirrYIslkT4acnczt

-- Dumped from database version 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)
-- Dumped by pg_dump version 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: hive_sources; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.hive_sources (
    id integer NOT NULL,
    mission_id text,
    url text,
    domain text,
    title text,
    snippet text,
    source_type text,
    discovered_at timestamp with time zone,
    score_relevance integer,
    score_freshness integer,
    score_density integer,
    score_authority integer,
    score_accessibility integer,
    score_uniqueness integer,
    score_depth integer,
    score_total integer,
    status text,
    harvest_method text
);


ALTER TABLE public.hive_sources OWNER TO postgres;

--
-- Name: hive_sources hive_sources_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.hive_sources
    ADD CONSTRAINT hive_sources_pkey PRIMARY KEY (id);


--
-- Name: idx_sources_domain; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_sources_domain ON public.hive_sources USING btree (domain);


--
-- Name: idx_sources_mission; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_sources_mission ON public.hive_sources USING btree (mission_id);


--
-- Name: idx_sources_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_sources_status ON public.hive_sources USING btree (status);


--
-- Name: TABLE hive_sources; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.hive_sources TO hive_app;


--
-- PostgreSQL database dump complete
--

\unrestrict Sb0SmDoFoX44NpJD1RpfOWuQiJitIRUE7ffYHm8vSo38m5qirrYIslkT4acnczt

