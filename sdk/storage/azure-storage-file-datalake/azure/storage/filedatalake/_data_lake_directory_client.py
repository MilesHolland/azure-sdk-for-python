# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------
# pylint: disable=docstring-keyword-should-match-keyword-only

import functools
from typing import (
    Any, cast, Dict, Optional, Union,
    TYPE_CHECKING
)
from urllib.parse import quote, unquote
from typing_extensions import Self

from azure.core.paging import ItemPaged
from azure.core.pipeline import Pipeline
from azure.core.tracing.decorator import distributed_trace

from ._data_lake_file_client import DataLakeFileClient
from ._deserialize import deserialize_dir_properties
from ._list_paths_helper import PathPropertiesPaged
from ._models import DirectoryProperties, FileProperties
from ._path_client import PathClient
from ._path_client_helpers import _parse_rename_path
from ._shared.base_client import parse_connection_str, TransportWrapper

if TYPE_CHECKING:
    from azure.core.credentials import AzureNamedKeyCredential, AzureSasCredential, TokenCredential
    from datetime import datetime
    from ._models import PathProperties


class DataLakeDirectoryClient(PathClient):
    """A client to interact with the DataLake directory, even if the directory may not yet exist.

    For operations relating to a specific subdirectory or file under the directory, a directory client or file client
    can be retrieved using the :func:`~get_sub_directory_client` or :func:`~get_file_client` functions.

    :param str account_url:
        The URI to the storage account.
    :param file_system_name:
        The file system for the directory or files.
    :type file_system_name: str
    :param directory_name:
        The whole path of the directory. eg. {directory under file system}/{directory to interact with}
    :type directory_name: str
    :param credential:
        The credentials with which to authenticate. This is optional if the
        account URL already has a SAS token. The value can be a SAS token string,
        an instance of a AzureSasCredential or AzureNamedKeyCredential from azure.core.credentials,
        an account shared access key, or an instance of a TokenCredentials class from azure.identity.
        If the resource URI already contains a SAS token, this will be ignored in favor of an explicit credential
        - except in the case of AzureSasCredential, where the conflicting SAS tokens will raise a ValueError.
        If using an instance of AzureNamedKeyCredential, "name" should be the storage account name, and "key"
        should be the storage account key.
    :type credential:
        ~azure.core.credentials.AzureNamedKeyCredential or
        ~azure.core.credentials.AzureSasCredential or
        ~azure.core.credentials.TokenCredential or
        str or Dict[str, str] or None
    :keyword str api_version:
        The Storage API version to use for requests. Default value is the most recent service version that is
        compatible with the current SDK. Setting to an older version may result in reduced feature compatibility.
    :keyword str audience: The audience to use when requesting tokens for Azure Active Directory
        authentication. Only has an effect when credential is of type TokenCredential. The value could be
        https://storage.azure.com/ (default) or https://<account>.blob.core.windows.net.

    .. admonition:: Example:

        .. literalinclude:: ../samples/datalake_samples_instantiate_client.py
            :start-after: [START instantiate_directory_client_from_conn_str]
            :end-before: [END instantiate_directory_client_from_conn_str]
            :language: python
            :dedent: 4
            :caption: Creating the DataLakeServiceClient from connection string.
    """

    url: str
    """The full endpoint URL to the file system, including SAS token if used."""
    primary_endpoint: str
    """The full primary endpoint URL."""
    primary_hostname: str
    """The hostname of the primary endpoint."""

    def __init__(
        self, account_url: str,
        file_system_name: str,
        directory_name: str,
        credential: Optional[Union[str, Dict[str, str], "AzureNamedKeyCredential", "AzureSasCredential", "TokenCredential"]] = None,  # pylint: disable=line-too-long
        **kwargs: Any
    ) -> None:
        super(DataLakeDirectoryClient, self).__init__(account_url, file_system_name, path_name=directory_name,
                                                      credential=credential, **kwargs)

    @classmethod
    def from_connection_string(
        cls, conn_str: str,
        file_system_name: str,
        directory_name: str,
        credential: Optional[Union[str, Dict[str, str], "AzureNamedKeyCredential", "AzureSasCredential", "TokenCredential"]] = None,  # pylint: disable=line-too-long
        **kwargs: Any
    ) -> Self:
        """
        Create DataLakeDirectoryClient from a Connection String.

        :param str conn_str:
            A connection string to an Azure Storage account.
        :param file_system_name:
            The name of file system to interact with.
        :type file_system_name: str
        :param credential:
            The credentials with which to authenticate. This is optional if the
            account URL already has a SAS token. The value can be a SAS token string,
            an instance of a AzureSasCredential or AzureNamedKeyCredential from azure.core.credentials,
            an account shared access key, or an instance of a TokenCredentials class from azure.identity.
            If the resource URI already contains a SAS token, this will be ignored in favor of an explicit credential
            - except in the case of AzureSasCredential, where the conflicting SAS tokens will raise a ValueError.
            If using an instance of AzureNamedKeyCredential, "name" should be the storage account name, and "key"
            should be the storage account key.
        :type credential:
            ~azure.core.credentials.AzureNamedKeyCredential or
            ~azure.core.credentials.AzureSasCredential or
            ~azure.core.credentials.TokenCredential or
            str or Dict[str, str] or None
        :param directory_name:
            The name of directory to interact with. The directory is under file system.
        :type directory_name: str
        :keyword str audience: The audience to use when requesting tokens for Azure Active Directory
            authentication. Only has an effect when credential is of type TokenCredential. The value could be
            https://storage.azure.com/ (default) or https://<account>.blob.core.windows.net.
        :return: A DataLakeDirectoryClient.
        :rtype: ~azure.storage.filedatalake.DataLakeDirectoryClient
        """
        account_url, _, credential = parse_connection_str(conn_str, credential, 'dfs')
        return cls(
            account_url, file_system_name=file_system_name, directory_name=directory_name,
            credential=credential, **kwargs)

    @distributed_trace
    def create_directory(
        self, metadata: Optional[Dict[str, str]] = None,
        **kwargs: Any
    ) -> Dict[str, Union[str, "datetime"]]:
        """
        Create a new directory.

        :param metadata:
            Name-value pairs associated with the file as metadata.
        :type metadata: Dict[str, str]
        :keyword ~azure.storage.filedatalake.ContentSettings content_settings:
            ContentSettings object used to set path properties.
        :keyword lease:
            Required if the file has an active lease. Value can be a DataLakeLeaseClient object
            or the lease ID as a string.
        :paramtype lease: ~azure.storage.filedatalake.DataLakeLeaseClient or str
        :keyword str umask:
            Optional and only valid if Hierarchical Namespace is enabled for the account.
            When creating a file or directory and the parent folder does not have a default ACL,
            the umask restricts the permissions of the file or directory to be created.
            The resulting permission is given by p & ^u, where p is the permission and u is the umask.
            For example, if p is 0777 and u is 0057, then the resulting permission is 0720.
            The default permission is 0777 for a directory and 0666 for a file. The default umask is 0027.
            The umask must be specified in 4-digit octal notation (e.g. 0766).
        :keyword str owner:
            The owner of the file or directory.
        :keyword str group:
            The owning group of the file or directory.
        :keyword str acl:
            Sets POSIX access control rights on files and directories. The value is a
            comma-separated list of access control entries. Each access control entry (ACE) consists of a
            scope, a type, a user or group identifier, and permissions in the format
            "[scope:][type]:[id]:[permissions]".
        :keyword str lease_id:
            Proposed lease ID, in a GUID string format. The DataLake service returns
            400 (Invalid request) if the proposed lease ID is not in the correct format.
        :keyword int lease_duration:
            Specifies the duration of the lease, in seconds, or negative one
            (-1) for a lease that never expires. A non-infinite lease can be
            between 15 and 60 seconds. A lease duration cannot be changed
            using renew or change.
        :keyword str permissions:
            Optional and only valid if Hierarchical Namespace
            is enabled for the account. Sets POSIX access permissions for the file
            owner, the file owning group, and others. Each class may be granted
            read, write, or execute permission.  The sticky bit is also supported.
            Both symbolic (rwxrw-rw-) and 4-digit octal notation (e.g. 0766) are
            supported.
        :keyword ~datetime.datetime if_modified_since:
            A DateTime value. Azure expects the date value passed in to be UTC.
            If timezone is included, any non-UTC datetimes will be converted to UTC.
            If a date is passed in without timezone info, it is assumed to be UTC.
            Specify this header to perform the operation only
            if the resource has been modified since the specified time.
        :keyword ~datetime.datetime if_unmodified_since:
            A DateTime value. Azure expects the date value passed in to be UTC.
            If timezone is included, any non-UTC datetimes will be converted to UTC.
            If a date is passed in without timezone info, it is assumed to be UTC.
            Specify this header to perform the operation only if
            the resource has not been modified since the specified date/time.
        :keyword str etag:
            An ETag value, or the wildcard character (*). Used to check if the resource has changed,
            and act according to the condition specified by the `match_condition` parameter.
        :keyword ~azure.core.MatchConditions match_condition:
            The match condition to use upon the etag.
        :keyword ~azure.storage.filedatalake.CustomerProvidedEncryptionKey cpk:
            Encrypts the data on the service-side with the given key.
            Use of customer-provided keys must be done over HTTPS.
        :keyword int timeout:
            Sets the server-side timeout for the operation in seconds. For more details see
            https://learn.microsoft.com/rest/api/storageservices/setting-timeouts-for-blob-service-operations.
            This value is not tracked or validated on the client. To configure client-side network timesouts
            see `here <https://github.com/Azure/azure-sdk-for-python/tree/main/sdk/storage/azure-storage-file-datalake
            #other-client--per-operation-configuration>`_.
        :return: A dictionary of response headers.
        :rtype: Dict[str, Union[str, ~datetime.datetime]]

        .. admonition:: Example:

            .. literalinclude:: ../samples/datalake_samples_directory.py
                :start-after: [START create_directory]
                :end-before: [END create_directory]
                :language: python
                :dedent: 8
                :caption: Create directory.
        """
        return self._create('directory', metadata=metadata, **kwargs)

    @distributed_trace
    def delete_directory(self, **kwargs: Any) -> None:
        """
        Marks the specified directory for deletion.

        :keyword lease:
            Required if the file has an active lease. Value can be a LeaseClient object
            or the lease ID as a string.
        :paramtype lease: ~azure.storage.filedatalake.DataLakeLeaseClient or str
        :keyword ~datetime.datetime if_modified_since:
            A DateTime value. Azure expects the date value passed in to be UTC.
            If timezone is included, any non-UTC datetimes will be converted to UTC.
            If a date is passed in without timezone info, it is assumed to be UTC.
            Specify this header to perform the operation only
            if the resource has been modified since the specified time.
        :keyword ~datetime.datetime if_unmodified_since:
            A DateTime value. Azure expects the date value passed in to be UTC.
            If timezone is included, any non-UTC datetimes will be converted to UTC.
            If a date is passed in without timezone info, it is assumed to be UTC.
            Specify this header to perform the operation only if
            the resource has not been modified since the specified date/time.
        :keyword str etag:
            An ETag value, or the wildcard character (*). Used to check if the resource has changed,
            and act according to the condition specified by the `match_condition` parameter.
        :keyword ~azure.core.MatchConditions match_condition:
            The match condition to use upon the etag.
        :keyword int timeout:
            Sets the server-side timeout for the operation in seconds. For more details see
            https://learn.microsoft.com/rest/api/storageservices/setting-timeouts-for-blob-service-operations.
            This value is not tracked or validated on the client. To configure client-side network timesouts
            see `here <https://github.com/Azure/azure-sdk-for-python/tree/main/sdk/storage/azure-storage-file-datalake
            #other-client--per-operation-configuration>`_.
        :returns: A dictionary of response headers.
        :rtype: Dict[str, Any]

        .. admonition:: Example:

            .. literalinclude:: ../samples/datalake_samples_directory.py
                :start-after: [START delete_directory]
                :end-before: [END delete_directory]
                :language: python
                :dedent: 4
                :caption: Delete directory.
        """
        return self._delete(recursive=True, **kwargs)  # type: ignore [return-value]

    @distributed_trace
    def get_directory_properties(self, **kwargs: Any) -> DirectoryProperties:
        """Returns all user-defined metadata, standard HTTP properties, and
        system properties for the directory. It does not return the content of the directory.

        :keyword lease:
            Required if the directory or file has an active lease. Value can be a DataLakeLeaseClient object
            or the lease ID as a string.
        :paramtype lease: ~azure.storage.filedatalake.DataLakeLeaseClient or str
        :keyword ~datetime.datetime if_modified_since:
            A DateTime value. Azure expects the date value passed in to be UTC.
            If timezone is included, any non-UTC datetimes will be converted to UTC.
            If a date is passed in without timezone info, it is assumed to be UTC.
            Specify this header to perform the operation only
            if the resource has been modified since the specified time.
        :keyword ~datetime.datetime if_unmodified_since:
            A DateTime value. Azure expects the date value passed in to be UTC.
            If timezone is included, any non-UTC datetimes will be converted to UTC.
            If a date is passed in without timezone info, it is assumed to be UTC.
            Specify this header to perform the operation only if
            the resource has not been modified since the specified date/time.
        :keyword str etag:
            An ETag value, or the wildcard character (*). Used to check if the resource has changed,
            and act according to the condition specified by the `match_condition` parameter.
        :keyword ~azure.core.MatchConditions match_condition:
            The match condition to use upon the etag.
        :keyword ~azure.storage.filedatalake.CustomerProvidedEncryptionKey cpk:
            Decrypts the data on the service-side with the given key.
            Use of customer-provided keys must be done over HTTPS.
            Required if the directory was created with a customer-provided key.
        :keyword bool upn:
            If True, the user identity values returned in the x-ms-owner, x-ms-group,
            and x-ms-acl response headers will be transformed from Azure Active Directory Object IDs to User
            Principal Names in the owner, group, and acl fields of
            :class:`~azure.storage.filedatalake.DirectoryProperties`. If False, the values will be returned
            as Azure Active Directory Object IDs. The default value is False. Note that group and application
            Object IDs are not translate because they do not have unique friendly names.
        :keyword int timeout:
            Sets the server-side timeout for the operation in seconds. For more details see
            https://learn.microsoft.com/rest/api/storageservices/setting-timeouts-for-blob-service-operations.
            This value is not tracked or validated on the client. To configure client-side network timesouts
            see `here <https://github.com/Azure/azure-sdk-for-python/tree/main/sdk/storage/azure-storage-file-datalake
            #other-client--per-operation-configuration>`_.
        :returns:
            DirectoryProperties with all user-defined metadata, standard HTTP properties,
            and system properties for the directory. It does not return the content of the directory.
        :rtype: ~azure.storage.filedatalake.DirectoryProperties

        .. admonition:: Example:

            .. literalinclude:: ../samples/datalake_samples_directory.py
                :start-after: [START get_directory_properties]
                :end-before: [END get_directory_properties]
                :language: python
                :dedent: 4
                :caption: Getting the properties for a file/directory.
        """
        upn = kwargs.pop('upn', None)
        if upn:
            headers = kwargs.pop('headers', {})
            headers['x-ms-upn'] = str(upn)
            kwargs['headers'] = headers
        return cast(DirectoryProperties, self._get_path_properties(cls=deserialize_dir_properties, **kwargs))

    @distributed_trace
    def exists(self, **kwargs: Any) -> bool:
        """
        Returns True if a directory exists and returns False otherwise.

        :keyword int timeout:
            Sets the server-side timeout for the operation in seconds. For more details see
            https://learn.microsoft.com/rest/api/storageservices/setting-timeouts-for-blob-service-operations.
            This value is not tracked or validated on the client. To configure client-side network timesouts
            see `here <https://github.com/Azure/azure-sdk-for-python/tree/main/sdk/storage/azure-storage-file-datalake
            #other-client--per-operation-configuration>`_.
        :returns: True if a directory exists, False otherwise.
        :rtype: bool
        """
        return self._exists(**kwargs)

    @distributed_trace
    def rename_directory(self, new_name: str, **kwargs: Any) -> "DataLakeDirectoryClient":
        """
        Rename the source directory.

        :param str new_name:
            the new directory name the user want to rename to.
            The value must have the following format: "{filesystem}/{directory}/{subdirectory}".
        :keyword source_lease:
            A lease ID for the source path. If specified,
            the source path must have an active lease and the lease ID must
            match.
        :paramtype source_lease: ~azure.storage.filedatalake.DataLakeLeaseClient or str
        :keyword lease:
            Required if the file/directory has an active lease. Value can be a LeaseClient object
            or the lease ID as a string.
        :paramtype lease: ~azure.storage.filedatalake.DataLakeLeaseClient or str
        :keyword ~datetime.datetime if_modified_since:
            A DateTime value. Azure expects the date value passed in to be UTC.
            If timezone is included, any non-UTC datetimes will be converted to UTC.
            If a date is passed in without timezone info, it is assumed to be UTC.
            Specify this header to perform the operation only
            if the resource has been modified since the specified time.
        :keyword ~datetime.datetime if_unmodified_since:
            A DateTime value. Azure expects the date value passed in to be UTC.
            If timezone is included, any non-UTC datetimes will be converted to UTC.
            If a date is passed in without timezone info, it is assumed to be UTC.
            Specify this header to perform the operation only if
            the resource has not been modified since the specified date/time.
        :keyword str etag:
            An ETag value, or the wildcard character (*). Used to check if the resource has changed,
            and act according to the condition specified by the `match_condition` parameter.
        :keyword ~azure.core.MatchConditions match_condition:
            The match condition to use upon the etag.
        :keyword ~datetime.datetime source_if_modified_since:
            A DateTime value. Azure expects the date value passed in to be UTC.
            If timezone is included, any non-UTC datetimes will be converted to UTC.
            If a date is passed in without timezone info, it is assumed to be UTC.
            Specify this header to perform the operation only
            if the resource has been modified since the specified time.
        :keyword ~datetime.datetime source_if_unmodified_since:
            A DateTime value. Azure expects the date value passed in to be UTC.
            If timezone is included, any non-UTC datetimes will be converted to UTC.
            If a date is passed in without timezone info, it is assumed to be UTC.
            Specify this header to perform the operation only if
            the resource has not been modified since the specified date/time.
        :keyword str source_etag:
            The source ETag value, or the wildcard character (*). Used to check if the resource has changed,
            and act according to the condition specified by the `match_condition` parameter.
        :keyword ~azure.core.MatchConditions source_match_condition:
            The source match condition to use upon the etag.
        :keyword int timeout:
            Sets the server-side timeout for the operation in seconds. For more details see
            https://learn.microsoft.com/rest/api/storageservices/setting-timeouts-for-blob-service-operations.
            This value is not tracked or validated on the client. To configure client-side network timesouts
            see `here <https://github.com/Azure/azure-sdk-for-python/tree/main/sdk/storage/azure-storage-file-datalake
            #other-client--per-operation-configuration>`_.
        :returns: A DataLakeDirectoryClient with the renamed directory.
        :rtype: ~azure.storage.filedatalake.DataLakeDirectoryClient

        .. admonition:: Example:

            .. literalinclude:: ../samples/datalake_samples_directory.py
                :start-after: [START rename_directory]
                :end-before: [END rename_directory]
                :language: python
                :dedent: 4
                :caption: Rename the source directory.
        """
        new_file_system, new_path, new_dir_sas = _parse_rename_path(
            new_name, self.file_system_name, self._query_str, self._raw_credential)

        new_directory_client = DataLakeDirectoryClient(
            f"{self.scheme}://{self.primary_hostname}", new_file_system, directory_name=new_path,
            credential=self._raw_credential or new_dir_sas, _hosts=self._hosts, _configuration=self._config,
            _pipeline=self._pipeline)
        new_directory_client._rename_path(  # pylint: disable=protected-access
            f'/{quote(unquote(self.file_system_name))}/{quote(unquote(self.path_name))}{self._query_str}', **kwargs)
        return new_directory_client

    @distributed_trace
    def create_sub_directory(
        self, sub_directory: Union[DirectoryProperties, str],
        metadata: Optional[Dict[str, str]] = None,
        **kwargs: Any
    ) -> "DataLakeDirectoryClient":
        """
        Create a subdirectory and return the subdirectory client to be interacted with.

        :param sub_directory:
            The directory with which to interact. This can either be the name of the directory,
            or an instance of DirectoryProperties.
        :type sub_directory: str or ~azure.storage.filedatalake.DirectoryProperties
        :param metadata:
            Name-value pairs associated with the file as metadata.
        :type metadata: Dict[str, str]
        :keyword ~azure.storage.filedatalake.ContentSettings content_settings:
            ContentSettings object used to set path properties.
        :keyword lease:
            Required if the file has an active lease. Value can be a DataLakeLeaseClient object
            or the lease ID as a string.
        :paramtype lease: ~azure.storage.filedatalake.DataLakeLeaseClient or str
        :keyword str umask:
            Optional and only valid if Hierarchical Namespace is enabled for the account.
            When creating a file or directory and the parent folder does not have a default ACL,
            the umask restricts the permissions of the file or directory to be created.
            The resulting permission is given by p & ^u, where p is the permission and u is the umask.
            For example, if p is 0777 and u is 0057, then the resulting permission is 0720.
            The default permission is 0777 for a directory and 0666 for a file. The default umask is 0027.
            The umask must be specified in 4-digit octal notation (e.g. 0766).
        :keyword str owner:
            The owner of the file or directory.
        :keyword str group:
            The owning group of the file or directory.
        :keyword str acl:
            Sets POSIX access control rights on files and directories. The value is a
            comma-separated list of access control entries. Each access control entry (ACE) consists of a
            scope, a type, a user or group identifier, and permissions in the format
            "[scope:][type]:[id]:[permissions]".
        :keyword str lease_id:
            Proposed lease ID, in a GUID string format. The DataLake service returns
            400 (Invalid request) if the proposed lease ID is not in the correct format.
        :keyword int lease_duration:
            Specifies the duration of the lease, in seconds, or negative one
            (-1) for a lease that never expires. A non-infinite lease can be
            between 15 and 60 seconds. A lease duration cannot be changed
            using renew or change.
        :keyword str permissions:
            Optional and only valid if Hierarchical Namespace
            is enabled for the account. Sets POSIX access permissions for the file
            owner, the file owning group, and others. Each class may be granted
            read, write, or execute permission.  The sticky bit is also supported.
            Both symbolic (rwxrw-rw-) and 4-digit octal notation (e.g. 0766) are
            supported.
        :keyword ~datetime.datetime if_modified_since:
            A DateTime value. Azure expects the date value passed in to be UTC.
            If timezone is included, any non-UTC datetimes will be converted to UTC.
            If a date is passed in without timezone info, it is assumed to be UTC.
            Specify this header to perform the operation only
            if the resource has been modified since the specified time.
        :keyword ~datetime.datetime if_unmodified_since:
            A DateTime value. Azure expects the date value passed in to be UTC.
            If timezone is included, any non-UTC datetimes will be converted to UTC.
            If a date is passed in without timezone info, it is assumed to be UTC.
            Specify this header to perform the operation only if
            the resource has not been modified since the specified date/time.
        :keyword str etag:
            An ETag value, or the wildcard character (*). Used to check if the resource has changed,
            and act according to the condition specified by the `match_condition` parameter.
        :keyword ~azure.core.MatchConditions match_condition:
            The match condition to use upon the etag.
        :keyword ~azure.storage.filedatalake.CustomerProvidedEncryptionKey cpk:
            Encrypts the data on the service-side with the given key.
            Use of customer-provided keys must be done over HTTPS.
        :keyword int timeout:
            Sets the server-side timeout for the operation in seconds. For more details see
            https://learn.microsoft.com/rest/api/storageservices/setting-timeouts-for-blob-service-operations.
            This value is not tracked or validated on the client. To configure client-side network timesouts
            see `here <https://github.com/Azure/azure-sdk-for-python/tree/main/sdk/storage/azure-storage-file-datalake
            #other-client--per-operation-configuration>`_.
        :returns: DataLakeDirectoryClient for the subdirectory.
        :rtype: ~azure.storage.filedatalake.DataLakeDirectoryClient
        """
        subdir = self.get_sub_directory_client(sub_directory)
        subdir.create_directory(metadata=metadata, **kwargs)
        return subdir

    @distributed_trace
    def delete_sub_directory(  # pylint: disable=delete-operation-wrong-return-type
        self, sub_directory: Union[DirectoryProperties, str],
        **kwargs: Any
    ) -> "DataLakeDirectoryClient":
        """
        Marks the specified subdirectory for deletion.

        :param sub_directory:
            The directory with which to interact. This can either be the name of the directory,
            or an instance of DirectoryProperties.
        :type sub_directory: str or ~azure.storage.filedatalake.DirectoryProperties
        :keyword lease:
            Required if the file has an active lease. Value can be a LeaseClient object
            or the lease ID as a string.
        :paramtype lease: ~azure.storage.filedatalake.DataLakeLeaseClient or str
        :keyword ~datetime.datetime if_modified_since:
            A DateTime value. Azure expects the date value passed in to be UTC.
            If timezone is included, any non-UTC datetimes will be converted to UTC.
            If a date is passed in without timezone info, it is assumed to be UTC.
            Specify this header to perform the operation only
            if the resource has been modified since the specified time.
        :keyword ~datetime.datetime if_unmodified_since:
            A DateTime value. Azure expects the date value passed in to be UTC.
            If timezone is included, any non-UTC datetimes will be converted to UTC.
            If a date is passed in without timezone info, it is assumed to be UTC.
            Specify this header to perform the operation only if
            the resource has not been modified since the specified date/time.
        :keyword str etag:
            An ETag value, or the wildcard character (*). Used to check if the resource has changed,
            and act according to the condition specified by the `match_condition` parameter.
        :keyword ~azure.core.MatchConditions match_condition:
            The match condition to use upon the etag.
        :keyword int timeout:
            Sets the server-side timeout for the operation in seconds. For more details see
            https://learn.microsoft.com/rest/api/storageservices/setting-timeouts-for-blob-service-operations.
            This value is not tracked or validated on the client. To configure client-side network timesouts
            see `here <https://github.com/Azure/azure-sdk-for-python/tree/main/sdk/storage/azure-storage-file-datalake
            #other-client--per-operation-configuration>`_.
        :returns: DataLakeDirectoryClient for the subdirectory.
        :rtype: ~azure.storage.filedatalake.DataLakeDirectoryClient
        """
        subdir = self.get_sub_directory_client(sub_directory)
        subdir.delete_directory(**kwargs)
        return subdir

    @distributed_trace
    def create_file(self, file: Union[FileProperties, str], **kwargs: Any) -> DataLakeFileClient:
        """
        Create a new file and return the file client to be interacted with.

        :param file:
            The file with which to interact. This can either be the name of the file,
            or an instance of FileProperties.
        :type file: str or ~azure.storage.filedatalake.FileProperties
        :keyword ~azure.storage.filedatalake.ContentSettings content_settings:
            ContentSettings object used to set path properties.
        :keyword metadata:
            Name-value pairs associated with the file as metadata.
        :type metadata: Dict[str, str]
        :keyword lease:
            Required if the file has an active lease. Value can be a DataLakeLeaseClient object
            or the lease ID as a string.
        :paramtype lease: ~azure.storage.filedatalake.DataLakeLeaseClient or str
        :keyword str umask:
            Optional and only valid if Hierarchical Namespace is enabled for the account.
            When creating a file or directory and the parent folder does not have a default ACL,
            the umask restricts the permissions of the file or directory to be created.
            The resulting permission is given by p & ^u, where p is the permission and u is the umask.
            For example, if p is 0777 and u is 0057, then the resulting permission is 0720.
            The default permission is 0777 for a directory and 0666 for a file. The default umask is 0027.
            The umask must be specified in 4-digit octal notation (e.g. 0766).
        :keyword str owner:
            The owner of the file or directory.
        :keyword str group:
            The owning group of the file or directory.
        :keyword str acl:
            Sets POSIX access control rights on files and directories. The value is a
            comma-separated list of access control entries. Each access control entry (ACE) consists of a
            scope, a type, a user or group identifier, and permissions in the format
            "[scope:][type]:[id]:[permissions]".
        :keyword str lease_id:
            Proposed lease ID, in a GUID string format. The DataLake service returns
            400 (Invalid request) if the proposed lease ID is not in the correct format.
        :keyword int lease_duration:
            Specifies the duration of the lease, in seconds, or negative one
            (-1) for a lease that never expires. A non-infinite lease can be
            between 15 and 60 seconds. A lease duration cannot be changed
            using renew or change.
        :keyword expires_on:
            The time to set the file to expiry.
            If the type of expires_on is an int, expiration time will be set
            as the number of milliseconds elapsed from creation time.
            If the type of expires_on is datetime, expiration time will be set
            absolute to the time provided. If no time zone info is provided, this
            will be interpreted as UTC.
        :paramtype expires_on: datetime or int
        :keyword str permissions:
            Optional and only valid if Hierarchical Namespace
            is enabled for the account. Sets POSIX access permissions for the file
            owner, the file owning group, and others. Each class may be granted
            read, write, or execute permission.  The sticky bit is also supported.
            Both symbolic (rwxrw-rw-) and 4-digit octal notation (e.g. 0766) are
            supported.
        :keyword ~datetime.datetime if_modified_since:
            A DateTime value. Azure expects the date value passed in to be UTC.
            If timezone is included, any non-UTC datetimes will be converted to UTC.
            If a date is passed in without timezone info, it is assumed to be UTC.
            Specify this header to perform the operation only
            if the resource has been modified since the specified time.
        :keyword ~datetime.datetime if_unmodified_since:
            A DateTime value. Azure expects the date value passed in to be UTC.
            If timezone is included, any non-UTC datetimes will be converted to UTC.
            If a date is passed in without timezone info, it is assumed to be UTC.
            Specify this header to perform the operation only if
            the resource has not been modified since the specified date/time.
        :keyword str etag:
            An ETag value, or the wildcard character (*). Used to check if the resource has changed,
            and act according to the condition specified by the `match_condition` parameter.
        :keyword ~azure.core.MatchConditions match_condition:
            The match condition to use upon the etag.
        :keyword ~azure.storage.filedatalake.CustomerProvidedEncryptionKey cpk:
            Encrypts the data on the service-side with the given key.
            Use of customer-provided keys must be done over HTTPS.
        :keyword int timeout:
            Sets the server-side timeout for the operation in seconds. For more details see
            https://learn.microsoft.com/rest/api/storageservices/setting-timeouts-for-blob-service-operations.
            This value is not tracked or validated on the client. To configure client-side network timesouts
            see `here <https://github.com/Azure/azure-sdk-for-python/tree/main/sdk/storage/azure-storage-file-datalake
            #other-client--per-operation-configuration>`_.
        :returns: A DataLakeFileClient with newly created file.
        :rtype: ~azure.storage.filedatalake.DataLakeFileClient
        """
        file_client = self.get_file_client(file)
        file_client.create_file(**kwargs)
        return file_client

    @distributed_trace
    def get_paths(
        self, *,
        recursive: bool = True,
        max_results: Optional[int] = None,
        upn: Optional[bool] = None,
        timeout: Optional[int] = None,
        **kwargs: Any
    ) -> ItemPaged["PathProperties"]:
        """Returns a generator to list the paths under specified file system and directory.
        The generator will lazily follow the continuation tokens returned by the service.

        :keyword bool recursive: Set True for recursive, False for iterative. The default value is True.
        :keyword Optional[int] max_results: An optional value that specifies the maximum
            number of items to return per page. If omitted or greater than 5,000, the
            response will include up to 5,000 items per page.
        :keyword Optional[bool] upn:
            If True, the user identity values returned in the x-ms-owner, x-ms-group,
            and x-ms-acl response headers will be transformed from Azure Active Directory Object IDs to User
            Principal Names in the owner, group, and acl fields of
            :class:`~azure.storage.filedatalake.PathProperties`. If False, the values will be returned
            as Azure Active Directory Object IDs. The default value is None. Note that group and application
            Object IDs are not translate because they do not have unique friendly names.
        :keyword Optional[int] timeout:
            Sets the server-side timeout for the operation in seconds. For more details see
            https://learn.microsoft.com/rest/api/storageservices/setting-timeouts-for-blob-service-operations.
            This value is not tracked or validated on the client. To configure client-side network timesouts
            see `here <https://github.com/Azure/azure-sdk-for-python/tree/main/sdk/storage/azure-storage-file-datalake
            #other-client--per-operation-configuration>`_. The default value is None.
        :returns: An iterable (auto-paging) response of PathProperties.
        :rtype: ~azure.core.paging.ItemPaged[~azure.storage.filedatalake.PathProperties]
        """
        hostname = self._hosts[self._location_mode]
        url = f"{self.scheme}://{hostname}/{quote(self.file_system_name)}"
        client = self._build_generated_client(url)
        command = functools.partial(
            client.file_system.list_paths,
            path=self.path_name,
            timeout=timeout,
            **kwargs
        )
        return ItemPaged(
            command, recursive, path=self.path_name, max_results=max_results,
            upn=upn, page_iterator_class=PathPropertiesPaged, **kwargs)

    def get_file_client(self, file: Union[FileProperties, str]) -> DataLakeFileClient:
        """Get a client to interact with the specified file.

        The file need not already exist.

        :param file:
            The file with which to interact. This can either be the name of the file,
            or an instance of FileProperties. eg. directory/subdirectory/file
        :type file: str or ~azure.storage.filedatalake.FileProperties
        :returns: A DataLakeFileClient.
        :rtype: ~azure.storage.filedatalake.DataLakeFileClient
        """
        if isinstance(file, FileProperties):
            file_path = file.get('name')
        else:
            file_path = self.path_name + '/' + str(file)

        _pipeline = Pipeline(
            transport=TransportWrapper(self._pipeline._transport), # pylint: disable = protected-access
            policies=self._pipeline._impl_policies # pylint: disable = protected-access
        )
        return DataLakeFileClient(
            self.url, self.file_system_name, file_path=file_path, credential=self._raw_credential,
            api_version=self.api_version,
            _hosts=self._hosts, _configuration=self._config, _pipeline=_pipeline)

    def get_sub_directory_client(self, sub_directory: Union[DirectoryProperties, str]) -> "DataLakeDirectoryClient":
        """Get a client to interact with the specified subdirectory of the current directory.

        The sub subdirectory need not already exist.

        :param sub_directory:
            The directory with which to interact. This can either be the name of the directory,
            or an instance of DirectoryProperties.
        :type sub_directory: str or ~azure.storage.filedatalake.DirectoryProperties
        :returns: A DataLakeDirectoryClient.
        :rtype: ~azure.storage.filedatalake.DataLakeDirectoryClient
        """
        if isinstance(sub_directory, DirectoryProperties):
            subdir_path = sub_directory.get('name')
        else:
            subdir_path = self.path_name + '/' + str(sub_directory)

        _pipeline = Pipeline(
            transport=TransportWrapper(self._pipeline._transport), # pylint: disable=protected-access
            policies=self._pipeline._impl_policies # pylint: disable=protected-access
        )
        return DataLakeDirectoryClient(
            self.url, self.file_system_name, directory_name=subdir_path, credential=self._raw_credential,
            api_version=self.api_version,
            _hosts=self._hosts, _configuration=self._config, _pipeline=_pipeline)
