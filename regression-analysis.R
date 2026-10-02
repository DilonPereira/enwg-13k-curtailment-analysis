library(readr)
library(dplyr)
library(lubridate)
library(fixest)
library(sandwich)
library(lmtest)

# Define file paths using relative paths for repository portability
CURTAILMENT_PATH <- "weekly_curtailment_national.csv"
GENERATION_PATH  <- "Actual_generation_202101010000_202609060000_Week.csv"

if (!file.exists(CURTAILMENT_PATH)) {
  stop("weekly_curtailment_national.csv not found.")
}
if (!file.exists(GENERATION_PATH)) {
  stop(paste("Generation file not found at:", GENERATION_PATH))
}

# 1. Load weekly curtailment
curt <- read_csv(CURTAILMENT_PATH, show_col_types = FALSE) %>%
  mutate(week_start = ymd(week_start))

# 2. Load and clean weekly generation
clean_numeric <- function(x) {
  x <- gsub(",", "", x)
  x <- na_if(x, "-")
  as.numeric(x)
}

gen <- read_delim(GENERATION_PATH, delim = ";", show_col_types = FALSE,
                  locale = locale(encoding = "UTF-8")) %>%
  rename(start_date = `Start date`) %>%
  mutate(
    week_start = mdy(start_date),
    wind_offshore_mwh = clean_numeric(`Wind offshore [MWh] Calculated resolutions`),
    wind_onshore_mwh  = clean_numeric(`Wind onshore [MWh] Calculated resolutions`),
    solar_mwh         = clean_numeric(`Photovoltaics [MWh] Calculated resolutions`),
    wind_solar_mwh    = wind_offshore_mwh + wind_onshore_mwh + solar_mwh
  ) %>%
  select(week_start, wind_solar_mwh)

# 3. Merge and build model variables
df <- curt %>%
  inner_join(gen, by = "week_start") %>%
  filter(!is.na(curtailed_mwh_national), curtailed_mwh_national > 0,
         !is.na(wind_solar_mwh), wind_solar_mwh > 0) %>%
  arrange(week_start) %>%
  mutate(
    log_curtailed   = log(curtailed_mwh_national),
    log_wind_solar  = log(wind_solar_mwh),
    month_of_year   = factor(month(week_start), levels = 1:12, labels = month.abb),
    post_13k        = as.integer(week_start >= ymd("2024-10-01")),
    time_trend      = as.numeric(week_start - min(week_start)) / 7,
    treatment_week  = as.numeric(ymd("2024-10-01") - min(week_start)) / 7,
    weeks_since_treatment = pmax(0, time_trend - treatment_week)
  )

cat("Weeks used:", nrow(df), "\n")
cat("Date range:", as.character(min(df$week_start)), "to", as.character(max(df$week_start)), "\n")
n_dropped <- nrow(curt) - nrow(df)
if (n_dropped > 0) {
  cat(n_dropped, "week(s) dropped due to missing/zero values or no generation match.\n")
}

# 4. Correlation check
corr_val <- cor(df$post_13k, df$time_trend)
cat("\nCorrelation between post_13k and time_trend:", round(corr_val, 3), "\n\n")

# 5. Interrupted Time Series model, weekly, no countertrade
model_weekly <- feols(
  log_curtailed ~ time_trend + post_13k + weeks_since_treatment + log_wind_solar | month_of_year,
  data = df, vcov = "hetero"
)
cat("================ WEEKLY ITS MODEL (no countertrade control) ================\n")
summary(model_weekly)

# 6. Newey-West (HAC) Standard Errors
model_weekly_lm <- lm(
  log_curtailed ~ time_trend + post_13k + weeks_since_treatment + log_wind_solar + month_of_year,
  data = df
)
cat("\n================ SAME MODEL, NEWEY-WEST (HAC, lag=8) ================\n")
print(coeftest(model_weekly_lm, vcov = NeweyWest(model_weekly_lm, lag = 8, prewhite = FALSE)))
cat("\n---------------- Sensitivity check: lag=4 ----------------\n")
print(coeftest(model_weekly_lm, vcov = NeweyWest(model_weekly_lm, lag = 4, prewhite = FALSE)))
cat("\n---------------- Sensitivity check: automatic lag selection ----------------\n")
print(coeftest(model_weekly_lm, vcov = NeweyWest(model_weekly_lm, prewhite = FALSE)))

# 7. Residual check for outlier weeks
df$resid_weekly <- resid(model_weekly_lm)
cat("\n================ LARGEST RESIDUALS (outlier weeks) ================\n")
df %>%
  select(week_start, resid_weekly) %>%
  arrange(desc(abs(resid_weekly))) %>%
  head(10) %>%
  print()

# 8. Save etable output
etable(model_weekly, file = "regression_results_weekly.txt", replace = TRUE)
cat("\nSaved regression_results_weekly.txt\n")

# 9. Robustness: trim early weeks
TRIM_BEFORE <- ymd("2021-11-15")
df_trimmed <- df %>% filter(week_start >= TRIM_BEFORE)
cat("\nWeeks after trimming pre-", as.character(TRIM_BEFORE), ":", nrow(df_trimmed), "\n")

model_weekly_trimmed <- feols(
  log_curtailed ~ time_trend + post_13k + weeks_since_treatment + log_wind_solar | month_of_year,
  data = df_trimmed, vcov = "hetero"
)
cat("\n================ WEEKLY ITS MODEL, EARLY WEEKS TRIMMED ================\n")
summary(model_weekly_trimmed)

model_weekly_trimmed_lm <- lm(
  log_curtailed ~ time_trend + post_13k + weeks_since_treatment + log_wind_solar + month_of_year,
  data = df_trimmed
)
cat("\n---------------- Same trimmed model, Newey-West (lag=8) ----------------\n")
print(coeftest(model_weekly_trimmed_lm, vcov = NeweyWest(model_weekly_trimmed_lm, lag = 8, prewhite = FALSE)))
cat("\n---------------- Same trimmed model, Newey-West (lag=4) ----------------\n")
print(coeftest(model_weekly_trimmed_lm, vcov = NeweyWest(model_weekly_trimmed_lm, lag = 4, prewhite = FALSE)))

df_trimmed$resid_trimmed <- resid(model_weekly_trimmed_lm)
cat("\n================ LARGEST RESIDUALS AFTER TRIMMING ================\n")
df_trimmed %>%
  select(week_start, resid_trimmed) %>%
  arrange(desc(abs(resid_trimmed))) %>%
  head(10) %>%
  print()

# 10. Placebo tests
run_placebo <- function(data, placebo_date_str) {
  placebo_date <- ymd(placebo_date_str)
  d <- data %>%
    mutate(
      post_placebo = as.integer(week_start >= placebo_date),
      placebo_week = as.numeric(placebo_date - min(week_start)) / 7,
      weeks_since_placebo = pmax(0, time_trend - placebo_week)
    )
  m <- feols(
    log_curtailed ~ time_trend + post_placebo + weeks_since_placebo + log_wind_solar | month_of_year,
    data = d, vcov = "hetero"
  )
  ct <- summary(m)$coeftable
  cat(sprintf(
    "\nPlacebo date %s:  post_placebo p=%.4f (est=%.3f)   weeks_since_placebo p=%.4f (est=%.4f)\n",
    placebo_date_str,
    ct["post_placebo", "Pr(>|t|)"], ct["post_placebo", "Estimate"],
    ct["weeks_since_placebo", "Pr(>|t|)"], ct["weeks_since_placebo", "Estimate"]
  ))
  invisible(m)
}

cat("\n================ PLACEBO TESTS (fake treatment dates) ================\n")
placebo_dates <- c("2022-10-01", "2023-04-01", "2023-10-01", "2024-04-01")
invisible(lapply(placebo_dates, function(d) run_placebo(df_trimmed, d)))

# 11. Add nuclear phase-out control
NUCLEAR_DATE <- ymd("2023-04-15")
df_trimmed <- df_trimmed %>%
  mutate(
    post_nuclear = as.integer(week_start >= NUCLEAR_DATE),
    nuclear_week = as.numeric(NUCLEAR_DATE - min(week_start)) / 7,
    weeks_since_nuclear = pmax(0, time_trend - nuclear_week)
  )

model_weekly_nuclear <- feols(
  log_curtailed ~ time_trend + post_13k + weeks_since_treatment +
    post_nuclear + weeks_since_nuclear + log_wind_solar | month_of_year,
  data = df_trimmed, vcov = "hetero"
)
cat("\n================ MAIN MODEL + NUCLEAR PHASE-OUT CONTROL ================\n")
summary(model_weekly_nuclear)

model_weekly_nuclear_lm <- lm(
  log_curtailed ~ time_trend + post_13k + weeks_since_treatment +
    post_nuclear + weeks_since_nuclear + log_wind_solar + month_of_year,
  data = df_trimmed
)
cat("\n---------------- Same model, Newey-West (lag=8) ----------------\n")
print(coeftest(model_weekly_nuclear_lm, vcov = NeweyWest(model_weekly_nuclear_lm, lag = 8, prewhite = FALSE)))

run_placebo_with_nuclear <- function(data, placebo_date_str) {
  placebo_date <- ymd(placebo_date_str)
  d <- data %>%
    mutate(
      post_placebo = as.integer(week_start >= placebo_date),
      placebo_week = as.numeric(placebo_date - min(week_start)) / 7,
      weeks_since_placebo = pmax(0, time_trend - placebo_week)
    )
  m <- feols(
    log_curtailed ~ time_trend + post_placebo + weeks_since_placebo +
      post_nuclear + weeks_since_nuclear + log_wind_solar | month_of_year,
    data = d, vcov = "hetero"
  )
  ct <- summary(m)$coeftable
  cat(sprintf(
    "\nPlacebo date %s:  post_placebo p=%.4f (est=%.3f)   weeks_since_placebo p=%.4f (est=%.4f)\n",
    placebo_date_str,
    ct["post_placebo", "Pr(>|t|)"], ct["post_placebo", "Estimate"],
    ct["weeks_since_placebo", "Pr(>|t|)"], ct["weeks_since_placebo", "Estimate"]
  ))
  invisible(m)
}

cat("\n================ PLACEBO TESTS, WITH NUCLEAR CONTROL HELD CONSTANT ================\n")
invisible(lapply(placebo_dates, function(d) run_placebo_with_nuclear(df_trimmed, d)))

# 12. Regression tables
dict <- c(
  "time_trend"            = "Time trend (weeks)",
  "post_13k"              = "Post §13k EnWG (level shift)",
  "weeks_since_treatment" = "Weeks since §13k × slope change",
  "post_nuclear"          = "Post nuclear phase-out (level)",
  "weeks_since_nuclear"   = "Weeks since nuclear × slope",
  "log_wind_solar"        = "log(Wind + Solar generation)"
)

cat("\n================ PUBLICATION TABLE (console preview) ================\n")

etable(
  model_weekly,
  model_weekly_trimmed,
  model_weekly_nuclear,
  headers  = c("(1) Full sample", "(2) Trimmed sample", "(3) + Nuclear control"),
  dict     = dict,
  se.below = TRUE,
  fitstat  = ~ n + r2 + ar2,
  title    = "Effect of §13k EnWG trial phase on log(national renewable curtailment) — Weekly ITS",
  notes    = c(
    "Heteroskedasticity-robust (HC1) standard errors in parentheses.",
    "All models include month-of-year fixed effects.",
    "Column (2) drops weeks before 15 Nov 2021 (data-quality outliers).",
    "Column (3) additionally controls for the final nuclear phase-out (15 Apr 2023).",
    "Significance levels: * p<0.1, ** p<0.05, *** p<0.01"
  )
)

# Export plain text table
etable(
  model_weekly,
  model_weekly_trimmed,
  model_weekly_nuclear,
  headers  = c("(1) Full sample", "(2) Trimmed sample", "(3) + Nuclear control"),
  dict     = dict,
  se.below = TRUE,
  fitstat  = ~ n + r2 + ar2,
  title    = "Effect of §13k EnWG trial phase on log(national renewable curtailment) — Weekly ITS",
  notes    = c(
    "Heteroskedasticity-robust (HC1) standard errors in parentheses.",
    "All models include month-of-year fixed effects.",
    "Column (2) drops weeks before 15 Nov 2021 (data-quality outliers).",
    "Column (3) additionally controls for the final nuclear phase-out (15 Apr 2023).",
    "Significance levels: * p<0.1, ** p<0.05, *** p<0.01"
  ),
  file     = "regression_table_weekly.txt",
  replace  = TRUE
)

# Export LaTeX table
etable(
  model_weekly,
  model_weekly_trimmed,
  model_weekly_nuclear,
  headers  = c("(1) Full sample", "(2) Trimmed sample", "(3) + Nuclear control"),
  dict     = dict,
  se.below = TRUE,
  fitstat  = ~ n + r2 + ar2,
  title    = "Effect of §13k EnWG trial phase on log(national renewable curtailment) — Weekly ITS",
  notes    = c(
    "Heteroskedasticity-robust (HC1) standard errors in parentheses.",
    "All models include month-of-year fixed effects.",
    "Column (2) drops weeks before 15 Nov 2021 (data-quality outliers).",
    "Column (3) additionally controls for the final nuclear phase-out (15 Apr 2023).",
    "Significance levels: * p$<$0.1, ** p$<$0.05, *** p$<$0.01"
  ),
  tex      = TRUE,
  file     = "regression_table_weekly.tex",
  replace  = TRUE
)