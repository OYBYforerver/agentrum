{{- define "agentrum.fullname" -}}
{{- printf "%s" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "agentrum.databaseUrl" -}}
{{- if .Values.database.existingSecret -}}
{{- printf "%s" (tpl .Values.database.existingSecret .) -}}
{{- else -}}
{{- .Values.database.url -}}
{{- end -}}
{{- end -}}
